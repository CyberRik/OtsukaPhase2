"""FastAPI server for real-time Graph RAG visualization.

Provides websocket endpoint for streaming query execution events,
and HTTP endpoints for replay and analysis.
"""
import asyncio
import json
import logging
import queue
import threading
from typing import Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from senpai.graph.visualization import get_hub
from senpai.graph import query_instrumented

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active websocket connections."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.event_queue = queue.Queue()

    async def connect(self, websocket: WebSocket):
        """Accept a new websocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected websocket."""
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send a message to all connected clients."""
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to client: {e}")
                dead_connections.append(connection)

        # Clean up dead connections
        for conn in dead_connections:
            self.disconnect(conn)

    def queue_event(self, event: dict):
        """Queue an event for broadcast (called from sync code)."""
        self.event_queue.put(event)


manager = ConnectionManager()


async def process_event_queue():
    """Process queued events and broadcast them."""
    while True:
        try:
            # Non-blocking check for events
            event = manager.event_queue.get(timeout=0.1)
            await manager.broadcast(event)
        except queue.Empty:
            await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"Error processing event: {e}")


def on_visualization_event(event: dict):
    """Callback for visualization hub events (called from any context)."""
    # Queue the event for async broadcast
    manager.queue_event(event)
    logger.info(f"Event queued: {event.get('type')} (queue size: {manager.event_queue.qsize()})")


# Subscribe to the hub
hub = get_hub()
hub.subscribe(on_visualization_event)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifecycle."""
    logger.info("Visualization server starting")
    # Start the event queue processor
    queue_task = asyncio.create_task(process_event_queue())
    yield
    queue_task.cancel()
    logger.info("Visualization server stopping")


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Graph RAG Visualization",
        description="Real-time visualization of Graph RAG query processing",
        lifespan=lifespan,
    )

    # Enable CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.websocket("/ws/visualization")
    async def websocket_endpoint(websocket: WebSocket):
        """Websocket endpoint for real-time visualization events."""
        await manager.connect(websocket)
        try:
            # Send event history to new client
            for event in hub.event_history:
                await websocket.send_json(event)

            # Keep connection open and receive any messages
            while True:
                data = await websocket.receive_text()
                # Echo back or handle commands if needed
                logger.debug(f"Received from client: {data}")

        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"Websocket error: {e}")
            manager.disconnect(websocket)

    @app.get("/api/visualization/history")
    async def get_history():
        """Get the event history."""
        return {
            "events": hub.event_history,
            "total_events": len(hub.event_history),
            "active_connections": len(manager.active_connections),
        }

    @app.get("/api/visualization/health")
    async def health():
        """Health check endpoint."""
        return {
            "status": "ok",
            "event_history_size": len(hub.event_history),
            "active_connections": len(manager.active_connections),
        }

    @app.post("/api/visualization/clear-history")
    async def clear_history():
        """Clear the event history."""
        hub.event_history.clear()
        return {"status": "cleared"}

    # Query endpoints run the instrumented queries in this same process,
    # so events reach the hub the websocket clients are subscribed to.
    @app.post("/api/query/reps_who_win")
    def run_reps_who_win(category: str = "", industry: str = "",
                         after_activity_type: str = "", min_deals: int = 1):
        return query_instrumented.reps_who_win_viz(
            category=category, industry=industry,
            after_activity_type=after_activity_type, min_deals=min_deals,
        )

    @app.post("/api/query/account_graph")
    def run_account_graph(customer: str):
        return query_instrumented.account_graph_viz(customer=customer)

    @app.post("/api/query/connections")
    def run_connections(entity_a: str, entity_b: str):
        return query_instrumented.connections_viz(entity_a=entity_a, entity_b=entity_b)

    @app.post("/api/query/similar_by_graph")
    def run_similar_by_graph(deal_id: str, limit: int = 5):
        return query_instrumented.similar_by_graph_viz(deal_id=deal_id, limit=limit)

    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info",
    )
