from typing import List
from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accepts a new WebSocket connection and adds it to the list."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Removes a closed WebSocket connection from the list."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """Sends a message to a specific client."""
        try:
            # We use text mode to send JSON strings for structured data
            await websocket.send_text(message)
        except Exception as e:
            print(f"Error sending message to client: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: str):
        """Sends a message to all connected clients (not strictly needed for a per-client task, but useful)."""
        for connection in self.active_connections:
            await self.send_personal_message(message, connection)


# Global instance to be used by the FastAPI app
manager = ConnectionManager()
