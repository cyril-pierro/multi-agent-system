import json
from multiprocessing import Process, Queue
from typing import Any, Optional
from dataclasses import dataclass
from enum import Enum
from fastapi import WebSocket

from core.agents import (
    PlannerAgent,
    ExecutorAgent,
    AggregatorAgent,
    ClarifierAgent
)
from core.resolver import RunSolver
from tools.redis import RedisStateManager
from core.websocket import ConnectionManager


class TaskState(Enum):
    IDLE = 'IDLE'
    EXECUTING = 'EXECUTING'
    COMPLETED = 'COMPLETED'
    REFINEMENT_READY = 'REFINEMENT_READY'


@dataclass
class TaskResult:
    report: Optional[str] = None
    context: Optional[list] = None
    error: Optional[str] = None
    query: Optional[str] = None


# Single instance of the synchronous solver logic
new_resolver = RunSolver(
    planner=PlannerAgent(),
    executor=ExecutorAgent(),
    aggregator=AggregatorAgent()
)


def resolver_worker(
    current_instruction: str,
    original_task_query: str,
    initial_context: list[str],
    refinement_mode: bool,
    result_queue: Queue,
    stream_queue: Queue
) -> None:
    """Worker function to run the synchronous resolver in a separate process."""
    try:
        # NOTE: If any of your agents needed to stream their output, you'd
        # replace print() calls in agent.py/resolver.py with a function that
        # puts messages into a second Queue for the main process to relay.
        def worker_stream_func(message: str):
            stream_queue.put({"type": "PROGRESS", "message": message})

        final_report, updated_context = new_resolver.start(
            current_instruction=current_instruction,
            original_task_query=original_task_query,
            initial_context=initial_context,
            refinement_mode=refinement_mode,
            stream_func=worker_stream_func,
        )
        result_queue.put(TaskResult(
            report=final_report,
            context=updated_context,
            error=None,
            query=original_task_query
        ).__dict__)
    except Exception as e:
        result_queue.put(TaskResult(
            error=str(e),
            query=original_task_query
        ).__dict__)

# --- ASYNCHRONOUS TASK RUNNER FOR WEBSOCKET ---


class TaskRunner:
    """
    Manages the state and process for a single client's task via WebSocket.
    """

    def __init__(self, session_id: str, state_manager: RedisStateManager, ws: WebSocket, manager: ConnectionManager):
        self.session_id = session_id
        self.state_manager = state_manager
        self.websocket = ws
        self.manager = manager
        self.current_state = TaskState.IDLE.value
        self.active_process: Optional[Process] = None
        self.result_queue: Queue = Queue()
        self.stream_queue: Queue = Queue()
        self.last_query = ""

    async def _send_status_update(self, status: str, payload: dict[str, Any] = None):
        """Helper to send structured JSON messages over the WebSocket."""
        if not self.websocket or self.websocket.client_state.value == 2:
            print(f"[{self.session_id}] SKIPPING send: WebSocket is disconnected.")
            return

        message = {
            "status": status,
            "session_id": self.session_id,
            "state": self.current_state,
            "payload": payload if payload is not None else {}
        }
        await self.manager.send_personal_message(json.dumps(message), self.websocket)

    def _get_agent_response(self, user_input: str) -> str:
        """Helper to get a response from a ClarifierAgent synchronously."""
        ClarifierAgent.initiate(user_input)
        return ClarifierAgent.run(stream_func=print)

    async def check_and_handle_completion(self):
        """Checks the background process for completion and handles results."""

        if not self.websocket or self.websocket.client_state.value == 2:
            return

        # 1. Check Stream Queue for Agent Progress Updates
        while not self.stream_queue.empty():
            try:
                stream_data = self.stream_queue.get(timeout=0.01)
                if stream_data.get("type") == "PROGRESS":
                    await self._send_status_update(
                        "PROGRESS_UPDATE",
                        {"message": stream_data["message"]}
                    )
                elif stream_data.get("type") == "ERROR":
                    await self._send_status_update(
                        "STREAM_ERROR",
                        {"message": stream_data["message"]}
                    )
            except Exception as e:
                print(f"[{self.session_id}] Error reading stream queue: {e}")

        if self.active_process and not self.active_process.is_alive():
            if not self.result_queue.empty():
                result = self.result_queue.get()
                self.active_process.join()
                self.active_process = None  # Clear process after join

                if result['error']:
                    self.last_query = ""  # Reset query on error
                    error_msg = f"Task Failed: {result['error']}"
                    print(f"[{self.session_id}] {error_msg}")
                    await self._send_status_update("ERROR", {"message": error_msg})
                    self.current_state = TaskState.IDLE.value
                else:
                    self.state_manager.save_state(
                        self.session_id,
                        result['query'],
                        result['context']
                    )
                    self.last_query = result['query']
                    print(f"[{self.session_id}] Report Complete.")
                    await self._send_status_update("COMPLETED", {
                        "report": result['report'],
                        "query": self.last_query
                    })
                    self.current_state = TaskState.REFINEMENT_READY.value
            else:
                # Process finished but queue empty (shouldn't happen often)
                print(
                    f"[{self.session_id}] Process finished, no result in queue. Resetting.")
                self.active_process.join()
                self.active_process = None
                self.last_query = ""
                self.current_state = TaskState.IDLE.value

        # Send a tick update if still executing
        if self.current_state == TaskState.EXECUTING.value:
            await self._send_status_update("TICK", {"message": "Still executing task in the background..."})

    async def handle_user_input(self, user_input: str):
        """Processes a new user message based on the current state."""

        if self.current_state == TaskState.EXECUTING.value:
            # Handle chat/status check during execution
            clarifier_query = f"User is asking a question mid-task: {user_input}. Current task: {self.last_query}"
            # This is synchronous, so it will block. In a high-traffic app,
            # you would use `await asyncio.to_thread(self._get_agent_response, clarifier_query)`
            # to run it in a separate thread. For this simple example, we keep it synchronous.
            clarifier_response = self._get_agent_response(clarifier_query)
            await self._send_status_update(
                "CHAT_RESPONSE",
                {"agent": "Clarifier", "response": clarifier_response}
            )
            return

        if self.current_state == TaskState.REFINEMENT_READY.value:
            # Start refinement task
            last_query, last_context = self.state_manager.load_state(
                self.session_id)

            if not last_context:
                await self._send_status_update("ERROR", {"message": "Context lost/expired. Please start a new task."})
                self.current_state = TaskState.IDLE.value
                return

            await self._start_task_process(user_input, last_query, last_context, True)
            self.current_state = TaskState.EXECUTING.value
            return

        if self.current_state == TaskState.IDLE.value:
            # Start new task
            self.last_query = user_input
            await self._start_task_process(user_input, user_input, [], False)
            self.current_state = TaskState.EXECUTING.value
            return

    async def _start_task_process(self, current_instruction: str, original_query: str, initial_context: list[str], refinement_mode: bool):
        """Initializes and starts a new background process for a task."""
        self.result_queue = Queue()
        self.stream_queue = Queue()

        process_name = f"Worker-{'Refine' if refinement_mode else 'NewTask'}-{self.session_id}"

        self.active_process = Process(
            target=resolver_worker,
            # Pass the new stream_queue
            args=(current_instruction, original_query, initial_context,
                  refinement_mode, self.result_queue, self.stream_queue),
            name=process_name
        )

        self.active_process.start()

        await self._send_status_update(
            "TASK_STARTED",
            {
                "message": f"Task started in background process {self.active_process.pid}...",
                "initial_query": original_query,
                "mode": "Refinement" if refinement_mode else "New Task"
            }
        )
