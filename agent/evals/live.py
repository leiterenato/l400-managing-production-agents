"""The real Gen AI Evaluation Service pipeline (Preview) — wired, guarded.

This is the ``--live`` path. It calls the actual platform APIs against your GCP
project; results appear in the Console's **Evaluation** tab (not ``.show()``,
which is a notebook renderer). It is guarded so it never runs by accident:

  * import of ``vertexai`` fails cleanly if the eval extra / creds are absent;
  * it requires ``EVAL_LIVE_CONFIRM=1`` so a stray ``--live`` doesn't spend.

The pipeline is the one from the demo doc, with ONE deliberate change (Fase 2):

    generate_conversation_scenarios   # platform generates INPUTS (shown, narrated)
      -> run_inference                # DETERMINISTIC single-turn over EDD prompts
      -> evaluate                     # our metrics: green invariant + amber judge
                                      #              + grey managed baselines
      -> generate_loss_clusters       # name the dominant failure pattern

Why deterministic inference (the change): the platform's user simulator is
non-deterministic — across runs it may never steer the agent into the
over-refund, leaving the green invariant vacuously 1.00 and the S3 payoff
unproven. So we DECOUPLE inference from the simulator: the scored run feeds
``run_inference`` a fixed set of EDD-derived prompts (single-turn, no
``user_simulator_config``), so the $500-on-$50 money bug fires on EVERY run.
``generate_conversation_scenarios`` still runs to SHOW the platform generating
inputs — it is just no longer on the critical path to the payoff.

EDD boundary (say it on stage): the platform generates the *inputs*; the
*criterion of correct* — the green ``refund_within_charge`` invariant — is
derived from the contract by us. Deterministic inference makes that even
sharper: the adversarial input itself is derived from the contract, not
stumbled upon by a random simulator. That is the part no tool gives you.
"""

from __future__ import annotations

import os
import sys


def _preview_generated_inputs(generated: object, limit: int = 3) -> None:
    """Print a few of the platform-generated starting prompts (best-effort).

    Purely for stage display — the shape of ``generate_conversation_scenarios``
    output is a Preview surface, so this never raises: a quirk in the preview
    must not sink the run.
    """

    try:
        # generate_conversation_scenarios returns an EvaluationDataset whose
        # generated inputs live in eval_dataset_df as a `starting_prompt` column
        # (plus a `conversation_plan`). (NOT eval_cases[*].prompt.)
        df = getattr(generated, "eval_dataset_df", None)
        if df is not None and "starting_prompt" in getattr(df, "columns", []):
            shown = 0
            for prompt in df["starting_prompt"].tolist():
                print(f"  - {str(prompt).strip()[:200]}")
                shown += 1
                if shown >= limit:
                    break
            if not shown:
                print("  (0 scenarios generated)")
            return
        print(f"  (generated dataset shape is Preview: {type(generated).__name__})")
    except Exception as exc:  # pragma: no cover - Preview surface
        print(f"  (preview skipped: {type(exc).__name__}: {str(exc)[:120]})")


def run_live() -> int:
    try:
        import vertexai
        from vertexai import types
    except Exception as exc:  # pragma: no cover
        print(
            "Live eval needs google-cloud-aiplatform[evaluation] + GCP creds.\n"
            f"  import failed: {exc}\n"
            "  run without --live for the offline gate.",
            file=sys.stderr,
        )
        return 2

    if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
        print(
            "Refusing to run the live pipeline without EVAL_LIVE_CONFIRM=1.\n"
            "This calls Preview APIs against your project and may incur cost.\n"
            "  EVAL_LIVE_CONFIRM=1 uv run python -m evals.run_offline --live",
            file=sys.stderr,
        )
        return 3

    # Load agent/.env so GOOGLE_CLOUD_PROJECT/LOCATION/MODEL/SCENARIO are set
    # (this module is run via `python -m`, which — unlike `adk` — does not
    # auto-load .env).
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    except Exception:
        pass

    # CRITICAL: run_offline's top-level imports already touched get_settings(),
    # caching SCENARIO from the *shell* env (where it is unset -> "healthy")
    # BEFORE load_dotenv ran. Drop that cache so the agent's fault injection
    # reads SCENARIO=refund_over_charge from .env — otherwise issue_refund never
    # over-pays and the money bug silently vanishes (invariant stays green).
    from financial_support.config import get_settings, reload_settings

    reload_settings()

    from financial_support import root_agent

    from .metrics import (
        build_invariant_metric,
        build_judge_metric,
        build_trajectory_metric,
        managed_metric_enums,
    )

    settings = get_settings()
    project = settings.project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    client = vertexai.Client(project=project, location=settings.location)

    # 1) Build our metrics. The green invariants are LOCAL custom_function
    # callables that import the contract directly (no drift), scored in-process
    # by the SDK. Local-callable metrics are NOT registered server-side — they go
    # straight into evaluate(). The amber judge is a server-side LLMMetric.
    invariant = build_invariant_metric()     # local callable (value)
    trajectory = build_trajectory_metric()   # local callable (path, beat B)
    judge = build_judge_metric(              # types.LLMMetric (server-side judge)
        project=project, location=settings.location
    )

    # 2) SHOW the platform generating INPUTS (user simulation — NOT the criterion
    # of right). This is narrated on stage to name the EDD boundary; it is NOT the
    # scored dataset (see step 3 for why). Kept small/cheap.
    # NOTE: the platform's user-simulator / default eval model is a Gemini 3.x
    # preview that lives ONLY in the global region (same split as our agent). The
    # eval client runs regional (us-central1), so we must consent to routing the
    # request cross-region with allow_cross_region_model=True. For regulated
    # audiences this flag is a data-residency decision worth naming on stage.
    agent_info = types.evals.AgentInfo.load_from_agent(agent=root_agent)
    generated = client.evals.generate_conversation_scenarios(
        agent_info=agent_info,
        allow_cross_region_model=True,
        config={
            "count": 3,
            "generation_instruction": (
                "Generate scenarios where a customer asks for a refund, including "
                "an adversarial one that requests more than the original charge."
            ),
        },
    )
    print("\n=== Platform-generated INPUTS (user simulation) ===")
    print("  The platform generates inputs; it does NOT know what 'correct' is.")
    _preview_generated_inputs(generated)

    # 3) Run the real agent over a DETERMINISTIC set of EDD-derived prompts.
    # Decoupled from the user simulator on purpose: single-turn inference (no
    # user_simulator_config) runs the agent once per prompt, so with
    # SCENARIO=refund_over_charge the $500-on-$50 money bug fires on EVERY run —
    # the S3 payoff is guaranteed, not left to a non-deterministic simulator.
    import pandas as pd

    from .scenarios import live_inference_rows

    rows = live_inference_rows()
    prompt_df = pd.DataFrame([{"prompt": r["prompt"]} for r in rows])
    print("\n=== Scored INPUTS (deterministic, EDD-derived) ===")
    for r in rows:
        print(f"  [{r['case_id']}] {r['prompt']}")

    traces = client.evals.run_inference(
        agent=root_agent,
        src=prompt_df,
        config={"allow_cross_region_model": True},
    )

    # 4) Score: our custom metrics + managed baselines.
    managed = [getattr(types.RubricMetric, n) for n in managed_metric_enums()]
    result = client.evals.evaluate(
        dataset=traces,
        metrics=[invariant, trajectory, judge, *managed],
    )

    # 5) Print the per-metric summary — THIS is the S3 payoff: the hard invariant
    # (refund_within_charge) fails on the money bug while the LLM judge
    # (tone_check) waves it through. "The green score lies", proven live.
    print("\n=== Evaluation summary (live) ===")
    for m in getattr(result, "summary_metrics", None) or []:
        name = getattr(m, "metric_name", None) or getattr(m, "metric", "?")
        mean = getattr(m, "mean_score", None)
        pass_rate = getattr(m, "pass_rate", None)
        n_valid = getattr(m, "num_cases_valid", None)
        n_err = getattr(m, "num_cases_error", None)
        mean_s = f"{mean:.2f}" if isinstance(mean, (int, float)) else str(mean)
        pr_s = f"{pass_rate:.0%}" if isinstance(pass_rate, (int, float)) else str(pass_rate)
        print(f"  {name:<28} mean={mean_s:<6} pass_rate={pr_s:<6} valid={n_valid} err={n_err}")

    # Dump the full result to disk so we can analyze per-case offline without
    # spending on another live run.
    try:
        import json as _json

        # model_dump() chokes on the pandas.DataFrame carried in
        # evaluation_dataset -> exclude that field before dumping.
        dumped = result.model_dump(
            mode="json", exclude_none=True, exclude={"evaluation_dataset"}
        )
        with open("/tmp/eval_result.json", "w", encoding="utf-8") as fh:
            _json.dump(dumped, fh, indent=2, default=str)
        print("\nwrote full result -> /tmp/eval_result.json")
    except Exception as exc:
        print(f"\nresult dump failed: {exc}")

    # 6) Name the dominant failure pattern. generate_loss_clusters is EXPERIMENTAL
    # and fussy about the result shape; keep it best-effort so a Preview quirk
    # never sinks the run. (Failure Clusters is really an S4 beat.)
    print("\n=== Loss clusters (experimental) ===")
    try:
        clusters = client.evals.generate_loss_clusters(
            eval_result=result, metric="refund_within_charge"
        )
        print(f"  {clusters}")
    except Exception as exc:  # pragma: no cover - Preview surface
        print(f"  (skipped: {type(exc).__name__}: {str(exc)[:160]})")

    print("\nLive eval done. See the Evaluation tab in the Cloud Console.")
    print(f"  project={project} location={settings.location}")
    return 0
