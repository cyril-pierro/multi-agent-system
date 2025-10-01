# main.py
import asyncio
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from tools.redis import RedisStateManager
from core.startup import TaskRunner
from core.websocket import manager as connection_manager

# Initialize FastAPI application
app = FastAPI(title="Multi-Agent WebSocket Solver")

# Initialize Redis Manager (assuming this is how it works in your setup)
redis_state_manager = RedisStateManager()
if not redis_state_manager.redis_client:
    print("\nFATAL: Redis connection failed. Please ensure Redis server is running.")
    # Exit or handle error appropriately in a production app

# Dictionary to hold the state for each client (TaskRunner instance)
active_task_runners: dict[str, TaskRunner] = {}

# Background task to monitor all active TaskRunners


async def background_task_monitor():
    """Periodically checks all active runners for task completion."""
    while True:
        # Iterate over a copy of the keys to allow modification during iteration
        for client_id in list(active_task_runners.keys()):
            runner = active_task_runners[client_id]
            try:
                await runner.check_and_handle_completion()
            except WebSocketDisconnect:
                # If disconnect happens here, it will be cleaned up in the main endpoint
                print(f"[{client_id}] Disconnect detected during monitor.")
            except Exception as e:
                print(f"[{client_id}] Unhandled error in monitor: {e}")
                # Clean up problematic runner if necessary
                if runner.active_process and runner.active_process.is_alive():
                    runner.active_process.terminate()
                del active_task_runners[client_id]

        await asyncio.sleep(1)  # Check every second


@app.on_event("startup")
async def startup_event():
    """Starts the background task on application startup."""
    # Ensure background monitor runs without blocking startup
    asyncio.create_task(background_task_monitor())


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    Handles the WebSocket connection for a specific client.
    The client_id also serves as the session_id for Redis context storage.
    """
    await connection_manager.connect(websocket)
    print(f"Client {client_id} connected.")

    # Initialize or retrieve the TaskRunner for this client
    if client_id not in active_task_runners:
        active_task_runners[client_id] = TaskRunner(
            session_id=client_id,
            state_manager=redis_state_manager,
            ws=websocket,
            manager=connection_manager
        )

    runner = active_task_runners[client_id]

    # Let the client know the current state upon connection
    await runner._send_status_update("CONNECTED")

    try:
        while True:
            # Wait for text input from the client (the user's query/chat message)
            data = await websocket.receive_text()
            print(f"[{client_id}] Received message: {data}")

            # Process the user input asynchronously
            await runner.handle_user_input(data)

    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
        print(f"Client {client_id} disconnected.")

        # NOTE: We do NOT delete the runner here, as its state might be needed
        # if the user reconnects (i.e., the task might still be running).
        # We rely on the monitor to handle process completion and the runner's
        # internal logic for state management.

    except Exception as e:
        print(f"[{client_id}] Unhandled exception in main loop: {e}")
        connection_manager.disconnect(websocket)
        if runner.active_process and runner.active_process.is_alive():
            print(f"[{client_id}] Terminating process due to error.")
            runner.active_process.terminate()


if __name__ == "__main__":
    print("\n--- Starting FastAPI WebSocket Server ---")
    # For a simple demo, you might delete the demo session on startup:
    DEMO_SESSION_ID = "user-abc-123-prod-session"
    if redis_state_manager.redis_client:
        redis_state_manager.redis_client.delete(
            redis_state_manager._get_key(DEMO_SESSION_ID))
        print("Cleared previous demo session context from Redis.")

    # Start the Uvicorn server
    # Use '127.0.0.1' and a different port if 8000 is blocked
    uvicorn.run(app, host="127.0.0.1", port=8000)
