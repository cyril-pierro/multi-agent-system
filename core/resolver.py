from core.agents import (
    PlannerAgent,
    ExecutorAgent,
    AggregatorAgent
)
from typing import Callable


class RunSolver:
    def __init__(
            self,
            planner: PlannerAgent,
            executor: ExecutorAgent,
            aggregator: AggregatorAgent,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.aggregator = aggregator

    def start(
        self,
        current_instruction: str,
        original_task_query: str,
        stream_func: Callable,
        initial_context: list[str] = [],
        refinement_mode: bool = False
    ) -> tuple[str, list[str]]:
        """
        Runs the full multi-agent workflow.
        current_instruction: The instruction for this specific run (e.g., initial task or refinement).
        original_task_query: The user's initial high-level request (used for Aggregator context).
        """

        intermediate_results = []
        context = list(initial_context)
        # all_sources = [] # Not needed for context persistence, so we omit saving it.

        stream_func("-" * 50)
        if refinement_mode:
            stream_func(
                f"[SYSTEM] Starting REFINEMENT run based on instruction: '{current_instruction}'")
            # In refinement mode, the plan is simply the user's new instruction to the Aggregator
            task_plan = [{'role': self.executor.get_details_for_agent('Aggregator')
                          ['role'], 'task': current_instruction}]
        else:
            stream_func(
                f"[SYSTEM] Starting Multi-Agent Task Solver for: '{original_task_query}'")
            # 1. Planning Phase
            # task_plan = plan_task(current_instruction)
            self.planner.initiate(current_instruction)
            task_plan = self.planner.run(stream_func)

        # 2. Execution Phase (Sequential Loop)
        for i, subtask in enumerate(task_plan):
            agent_role = subtask['role']
            instruction = subtask['task']

            stream_func("-" * 50)
            stream_func(
                f"[SYSTEM] Executing Subtask {i + 1}/{len(task_plan)}: {agent_role}")
            stream_func(f"[SYSTEM] Instruction: {instruction}")

            # Execute the task
            self.executor.initiate(agent_role, instruction, context)
            result_text, _ = self.executor.run(stream_func)

            # Store results and sources
            intermediate_results.append(
                {'role': agent_role, 'result': result_text})

            # Update context for the next agent
            context.append(
                f"Result from {agent_role} (Subtask {i + 1}):\n{result_text}")

            stream_func(
                f"[{agent_role}] Result stored. Length: {len(result_text)} characters.")

        # 3. Aggregation Phase
        self.aggregator.initiate(original_task_query, intermediate_results)
        final_report = self.aggregator.run(stream_func)

        # Return the final report and the complete context for future refinements
        return final_report, context
