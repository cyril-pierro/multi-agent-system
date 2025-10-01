from interfaces.agent import AgentInterface
from typing import Any, Tuple, Callable
from utils.request import make_api_call
import json


class ClarifierAgent(AgentInterface):
    """Uses the Clarifier agent for quick, simple chat responses."""

    @classmethod
    def initiate(cls, prompt: str) -> None:
        cls.prompt = prompt

    @property
    def agent_id(self):
        return "Clarifier"

    @classmethod
    def _generate_system_prompt(cls):
        return "You are the Clarification Agent. Respond concisely and professionally to the user's status checks or simple questions."

    @classmethod
    def _generate_payload(cls) -> dict[str, Any]:
        system_prompt = cls._generate_system_prompt()
        return {
            "contents": [{"parts": [{"text": cls.prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
        }

    @classmethod
    def run(cls, stream_func: Callable) -> str:  # Added stream_func
        stream_func(f"[{cls.agent_id}] Generating clarification response...")
        payload = cls._generate_payload()
        response = make_api_call(payload)
        result = response['candidates'][0]['content']['parts'][0]['text']
        stream_func(f"[{cls.agent_id}] Response generated.")
        return result


class PlannerAgent(AgentInterface):
    """Uses the Planner agent and structured JSON output to break down the user query."""

    @classmethod
    def initiate(cls, query: str) -> None:
        cls.query = query

    @classmethod
    @property
    def agent_id(cls):
        return "Planner"

    @classmethod
    def _generate_system_prompt(cls):
        return (
            "You are the Task Orchestrator. Your sole job is to break the following high-level business request "
            "into 2-3 sequential, specialized subtasks. You must use the most appropriate agent roles for each task "
            "from the available roles: Financial Analyst, Data Summarizer, and Report Generator. "
            "Output the result as a single JSON array."
        )

    @classmethod
    def _generate_payload(cls) -> dict[str, Any]:
        system_prompt = cls._generate_system_prompt()
        return {
            "contents": [{"parts": [{"text": f"Request: {cls.query}"}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "role": {"type": "STRING", "description": "The specialized agent role (e.g., Financial Analyst)."},
                            "task": {"type": "STRING", "description": "A specific, executable instruction for the agent."}
                        },
                        "required": ["role", "task"]
                    }
                }
            }
        }

    @classmethod
    def run(cls, stream_func: Callable) -> str:
        stream_func(f"[{cls.agent_id}] Breaking request down into subtasks...")
        payload = cls._generate_payload()
        response = make_api_call(payload)
        json_text = response['candidates'][0]['content']['parts'][0]['text']

        try:
            task_plan = json.loads(json_text)
            stream_func(
                f"[{cls.agent_id}] Plan generated: {len(task_plan)} subtasks identified.")
            return task_plan
        except json.JSONDecodeError:
            stream_func(
                f"[{cls.agent_id}] Failed to decode JSON response from LLM: {json_text}")
            raise


class ExecutorAgent(AgentInterface):

    """Runs a single agent on its assigned task, using context and tools."""

    __AGENTS = {
        'Planner': {'role': 'Task Planner', 'description': 'Breaks down request into subtasks.', 'tools': []},
        'Analyst': {'role': 'Financial Analyst', 'description': 'Gathers current financial data and trends.', 'tools': [{'google_search': {}}]},
        'Summarizer': {'role': 'Data Summarizer', 'description': 'Processes, organizes, and formats data into structured formats.', 'tools': []},
        'Aggregator': {'role': 'Report Generator', 'description': 'Combines all findings into the final, comprehensive business report.', 'tools': []},
        'Clarifier': {'role': 'Clarification Agent', 'description': 'Handles simple conversational chat, status checks, and acknowledgements.', 'tools': []},
    }

    @classmethod
    def initiate(cls, agent_role: str, instruction: str, context: list[str]):
        cls.agent_role = agent_role
        cls.instruction = instruction
        cls.context = context

    @classmethod
    @property
    def agent_id(self):
        return "Executor"

    @classmethod
    def get_details_for_agent(cls, agent: str) -> Any:
        return cls.__AGENTS.get(agent)

    @classmethod
    def _generate_system_prompt(cls):
        return (
            f"You are a highly specialized {cls.agent_role}. Your task is to strictly follow the instruction given: '{cls.instruction}'. "
            "Do not add conversational flair or commentary. "
            "Use the provided context for grounding your response, but keep the final output direct. "
            "Output the direct result required by the instruction (e.g., pure data, pure markdown table, or a concise summary)."
            f"\n\n--- PREVIOUS CONTEXT ---\n{cls.context[-1] if cls.context else 'None.'}"
        )

    @classmethod
    def _generate_payload(cls) -> dict[str, Any]:
        system_prompt = cls._generate_system_prompt()
        agent_key = next((k for k, v in cls.__AGENTS.items()
                          if v['role'] == cls.agent_role), 'Unknown')
        agent_config = cls.__AGENTS.get(agent_key, {})
        tools = agent_config.get('tools', [])
        return {
            "contents": [{"parts": [{"text": cls.instruction}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "tools": tools,
        }

    @classmethod
    def run(cls, stream_func: Callable) -> Tuple[str, list[dict[str, str]]]:
        stream_func(f"[{cls.agent_id}] Executing task for {cls.agent_role}...")
        payload = cls._generate_payload()
        response = make_api_call(payload)
        candidate = response['candidates'][0]
        text = candidate['content']['parts'][0]['text']
        sources = []
        grounding_metadata = candidate.get('groundingMetadata')
        if grounding_metadata and grounding_metadata.get('groundingAttributions'):
            sources = [
                {'uri': attr['web']['uri'], 'title': attr['web'].get(
                    'title', attr['web']['uri'])}
                for attr in grounding_metadata['groundingAttributions']
                if 'web' in attr
            ]
        stream_func(
            f"[{cls.agent_id}] Execution complete. Result size: {len(text)} chars.")
        return text, sources


class AggregatorAgent(AgentInterface):

    """Uses the Report Generator to combine all intermediate results into a final report."""

    @classmethod
    def initiate(cls, main_query: str, intermediate_results: list[dict[str, str]]):
        cls.main_query = main_query
        cls.intermediate_results = intermediate_results

    @classmethod
    @property
    def agent_id(cls):
        return "Aggregator"

    @classmethod
    def _generate_system_prompt(cls):
        return (
            "You are the Final Report Generator. Your job is to combine the provided intermediate results into a single, "
            "cohesive, comprehensive, and professionally formatted markdown report that directly and completely answers the "
            f"original user request: '{cls.main_query}'. Use markdown headings, clear formatting, and present data cleanly."
        )

    @classmethod
    def _generate_payload(cls) -> dict[str, Any]:
        system_prompt = cls._generate_system_prompt()
        full_context = "\n\n---\n\n".join([
            f"## Subtask {i + 1} Result ({res['role']}):\n{res['result']}"
            for i, res in enumerate(cls.intermediate_results)
        ])

        user_prompt = (
            f"ORIGINAL REQUEST: {cls.main_query}\n\n"
            f"---START OF INTERMEDIATE RESULTS---\n\n{full_context}\n\n"
            f"---END OF INTERMEDIATE RESULTS---\n\n"
            "Generate the final report now in markdown format."
        )

        return {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
        }

    @classmethod
    def run(cls, stream_func: Callable) -> str:  # Added stream_func
        stream_func(
            f"[{cls.agent_id}] All subtasks complete. Aggregating final report...")
        payload = cls._generate_payload()
        response = make_api_call(payload)
        result = response['candidates'][0]['content']['parts'][0]['text']
        stream_func(f"[{cls.agent_id}] Final report generated.")
        return result
