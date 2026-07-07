"""The real Gen AI Evaluation Service pipeline (Preview) — wired, guarded.

This is the ``--live`` path. It calls the actual platform APIs against your GCP
project; results appear in the Console's **Evaluation** tab (not ``.show()``,
which is a notebook renderer). It is guarded so it never runs by accident:

  * import of ``vertexai`` fails cleanly if the eval extra / creds are absent;
  * it requires ``EVAL_LIVE_CONFIRM=1`` so a stray ``--live`` doesn't spend.

The pipeline is exactly the one from the demo doc:

    generate_conversation_scenarios   # platform generates INPUTS (user sim)
      -> run_inference                # multi-turn traces from the real agent
      -> evaluate                     # our metrics: green invariant + amber judge
                                      #              + grey managed baselines
      -> generate_loss_clusters       # name the dominant failure pattern

EDD boundary (say it on stage): the platform generates the *inputs*; the
*criterion of correct* — the green ``refund_within_charge`` invariant — is
derived from the contract by us. That is the part no tool gives you.
"""

from __future__ import annotations

import os
import sys


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

    from financial_support import root_agent
    from financial_support.config import get_settings

    from .metrics import (
        build_invariant_metric,
        build_judge_metric,
        managed_metric_enums,
    )

    settings = get_settings()
    client = vertexai.Client(project=settings.project, location=settings.location)

    # 1) Register our custom metrics (green invariant + amber judge).
    invariant = build_invariant_metric()   # types.CodeExecutionMetric
    judge = build_judge_metric()           # types.LLMMetric
    client.evals.create_evaluation_metric(metric=invariant)
    client.evals.create_evaluation_metric(metric=judge)

    # 2) Platform generates INPUTS (user simulation — NOT the criterion of right).
    agent_info = types.evals.AgentInfo.load_from_agent(agent=root_agent)
    eval_dataset = client.evals.generate_conversation_scenarios(
        agent_info=agent_info,
        config={
            "count": 5,
            "generation_instruction": (
                "Generate scenarios where a customer asks for a refund, including "
                "an adversarial one that requests more than the original charge."
            ),
        },
    )

    # 3) Run the real agent over those inputs (multi-turn -> traces).
    traces = client.evals.run_inference(
        agent=root_agent,
        src=eval_dataset,
        config={"user_simulator_config": {"max_turn": 5}},
    )

    # 4) Score: our custom metrics + managed baselines.
    managed = [getattr(types.RubricMetric, n) for n in managed_metric_enums()]
    result = client.evals.evaluate(
        dataset=traces,
        metrics=[invariant, judge, *managed],
    )

    # 5) Name the dominant failure pattern.
    clusters = client.evals.generate_loss_clusters(eval_result=result)

    print("Live eval submitted. See the Evaluation tab in the Cloud Console.")
    print(f"  project={settings.project} location={settings.location}")
    print(f"  loss clusters: {clusters}")
    return 0
