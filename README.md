# 🤖 Multi-Agent WebSocket System (MAWS)

This repository contains the design and implementation for a real-time, streaming multi-agent system built on FastAPI WebSockets. It is designed to handle complex user queries by breaking them down into tasks executed by specialized agents.

---

## 💡 1. Design Decisions

The core architecture prioritizes **real-time feedback** and **concurrent task handling** for multiple clients.

### 1.1. Core Architectural Pattern: Asynchronous Worker

| Component                  | Technology / Language Feature   | Rationale                                                                                                                                                                                                                            |
| :------------------------- | :------------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Server Framework**       | **FastAPI** / Starlette (ASGI)  | Provides high-performance, non-blocking asynchronous I/O, essential for managing thousands of concurrent WebSocket connections.                                                                                                      |
| **Task Execution**         | `multiprocessing.Process`       | **Crucial:** LLM calls (`make_api_call`) and agent logic are **synchronous (blocking)**. To prevent one user's long-running task from freezing the entire FastAPI event loop, each major task is spawned in a separate OS process.   |
| **State & Communication**  | `multiprocessing.Queue`         | Used to safely pass results and, more importantly, **stream progress updates** from the synchronous worker process back to the asynchronous main thread for transmission over the WebSocket.                                         |
| **Connection & Broadcast** | `ConnectionManager` Class       | A Singleton pattern ensures the server maintains a centralized, thread-safe registry of all active `WebSocket` connections, enabling targeted messaging.                                                                             |
| **Agent State Management** | **Redis** (`RedisStateManager`) | Provides a persistent, out-of-process store for historical context (previous query, agent outputs). This is necessary because the _Task Runner_ process dies after completion, but its context is needed for the _Refinement_ stage. |

### 1.2. Agent Workflow (The Resolver)

The system enforces a structured sequence of agents to manage complexity and maintain consistency:

1.  **Planner Agent:** Receives the initial query and breaks it into a structured, sequential plan (a list of subtasks).
2.  **Executor Agent (xN):** Executes the subtasks defined by the Planner, gathering raw information and data. It uses the results of previous executors as context.
3.  **Aggregator Agent:** Takes all intermediate results and the original query to synthesize a final, coherent report in a user-friendly format (e.g., Markdown).
4.  **Clarifier Agent:** Runs separately from the main workflow. It handles real-time chat messages from the user while the main task is running, providing status updates or simple answers.

---

## ⏳ 2. Trade-Offs (Due to 24h Constraint)

The strict time constraint forced several pragmatic decisions, primarily impacting robustness and scalability:

| Trade-Off Made                                   | Impact / Consequence                                                                                                                                                                                                   | Future Improvement                                                                                                                                                                               |
| :----------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Simple `multiprocessing.Queue` for Streaming** | Highly efficient for this prototype, but lacks persistence. If the main server crashes, stream messages are lost. The primary WebSocket connection handling is also tightly coupled to the process ID.                 | Migrate to a dedicated asynchronous message queue (e.g., **Redis Pub/Sub** or **RabbitMQ**) to decouple the worker and the WebSocket sender.                                                     |
| **Limited Error Handling in Workers**            | The worker process sends a final `ERROR` to the result queue, but cleanup is simplistic. Race conditions (like sending a message while the socket is closing) require reactive `try/except` logic on the FastAPI side. | Implement more robust **heartbeat/ping-pong** mechanisms and add connection state checks _before_ sending messages to eliminate `RuntimeError: Unexpected ASGI message...`                       |
| **Synchronous Tool/LLM Calls (Mocked)**          | Assumed for this prototype. If the actual `make_api_call` was truly synchronous and long, it would still block the worker process entirely, leading to slow streaming.                                                 | Integrate an **Asynchronous LLM Client** (e.g., `httpx` or an async-native SDK) and run the entire agent logic using `async def` and `asyncio.create_task` instead of `multiprocessing.Process`. |
| **No Authentication/Authorization**              | The client ID is simply used in the URL path (`/ws/{session_id}`) without validation.                                                                                                                                  | Implement token-based authentication (e.g., JWT) passed via a query parameter or header, verified before `websocket.accept()`.                                                                   |

---

## 🚀 3. How to Run/Test the System

This guide assumes you have three Python files: `main.py`, `startup.py` (which contains `TaskRunner` and `resolver_worker`), and a basic `index.html` with a websocket client.

### 3.1. Prerequisites

1.  **FastAPI Setup:** Ensure all necessary Python files (`agent.py`, `resolver.py`, etc.) are in place.
2.  **Redis:** Redis must be running locally on the default port (`6379`).

### 3.2. Startup Procedure

1.  **Run the FastAPI Server:**

    ```bash
    uvicorn main:app --reload
    ```

    _The server will start, typically on `http://127.0.0.1:8000`._

2.  **Open the Client:**
    Open the `index.html` file in your web browser.

### 3.3. Testing the Workflow (Streaming)

1.  **Connect:**

    - Ensure the **WebSocket Host** is `ws://127.0.0.1:8000`.
    - Ensure the **Client/Session ID** is set (e.g., `TEST_CLIENT_1`).
    - Click **Connect**. The status should turn green.

2.  **Initial Task (Full Streaming Run):**

    - In the message input, type a complex request:
      ```
      Analyze the stock performance of Apple, Google, and Tesla over the last month and summarize the key findings.
      ```
    - Click **Send**.
    - **Observation:** The **Output Log** will immediately start showing `[AGENT STREAM]` messages as the task moves through the Planner, Executors, and Aggregator in the background worker process. This confirms the **streaming mechanism is working**.

3.  **Chat (Concurrent Clarifier Agent):**

    - While the initial task is still showing `[AGENT STREAM]` messages (i.e., the state is `EXECUTING`), type a simple message:
      ```
      What is the current status?
      ```
    - Click **Send**.
    - **Observation:** A `[CHAT_RESPONSE]` message will appear, handled by the Clarifier Agent, demonstrating that the main event loop remains responsive while the heavy task runs concurrently in the background process.

4.  **Refinement (State Management):**
    - Wait for the first task to finish (state becomes `REFINEMENT_READY`).
    - In the message input, type a refinement instruction:
      ```
      Rewrite the summary to focus only on Tesla's stock volatility.
      ```
    - Click **Send**.
    - **Observation:** The system will start a new task in `Refinement Mode`, retrieving the context (intermediate results) saved to **Redis**, and generating a new, refined report. This validates the persistence layer.
