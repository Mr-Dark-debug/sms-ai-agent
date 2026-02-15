"""
FastAPI Application - Main web application setup
===============================================

This module creates and configures the FastAPI application
with all necessary routes, middleware, and templates.
"""

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from core.config import Config, load_config
from core.database import Database, init_database
from core.logging import setup_logging, get_logger
from core.security import SecurityManager
from services.sms_handler import SMSHandler
from services.guardrails import GuardrailSystem
from services.ai_responder import AIResponder
from rules.engine import RulesEngine
from llm.factory import create_llm_provider

logger = get_logger("web.app")


def create_app(
    config: Optional[Config] = None,
    database: Optional[Database] = None,
    debug: bool = False
) -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Args:
        config: Application configuration
        database: Database instance
        debug: Enable debug mode
        
    Returns:
        Configured FastAPI application
    """
    # Load configuration if not provided
    if config is None:
        config = load_config()
    
    # Setup logging
    setup_logging(
        log_dir=config.log_dir,
        log_level="DEBUG" if debug else "INFO",
        console_output=True
    )
    
    # Initialize database if not provided
    if database is None:
        db_path = os.path.join(config.data_dir, "sms_agent.db")
        database = init_database(db_path)
    
    # Create FastAPI app
    app = FastAPI(
        title="SMS AI Agent",
        description="Web interface for SMS AI Agent",
        version="1.0.0",
        debug=debug or config.debug,
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Get templates directory
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    
    # Setup Jinja2 templates
    templates = Jinja2Templates(directory=str(templates_dir))
    
    # Setup static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    
    # Initialize services
    security_manager = SecurityManager(
        config_dir=config.config_dir,
        data_dir=config.data_dir
    )
    
    guardrails = GuardrailSystem(
        max_length=config.guardrail.max_response_length,
        block_phone_numbers=config.guardrail.block_phone_numbers,
        block_emails=config.guardrail.block_email_addresses,
        block_urls=config.guardrail.block_links,
        security_manager=security_manager
    )
    
    rules_engine = RulesEngine(config_dir=config.config_dir)
    
    sms_handler = SMSHandler(
        timeout=config.sms.sms_timeout
    )
    
    ai_responder = AIResponder(
        config=config,
        database=database,
        guardrails=guardrails,
        rules_engine=rules_engine,
        personality_path=os.path.join(config.config_dir, "personality.md"),
        agent_path=os.path.join(config.config_dir, "agent.md")
    )
    
    # Store services in app state
    app.state.config = config
    app.state.database = database
    app.state.security = security_manager
    app.state.guardrails = guardrails
    app.state.rules_engine = rules_engine
    app.state.sms_handler = sms_handler
    app.state.ai_responder = ai_responder
    app.state.templates = templates
    
    # Mount static files
    if (static_dir / "css").exists():
        app.mount("/static/css", StaticFiles(directory=str(static_dir / "css")), name="css")
    if (static_dir / "js").exists():
        app.mount("/static/js", StaticFiles(directory=str(static_dir / "js")), name="js")
    
    # Include routes
    from .routes import router as main_router
    app.include_router(main_router, prefix="")
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc) if debug else "An error occurred"}
        )
    
    logger.info("Web application created")
    
    return app


def run_app(
    host: str = "127.0.0.1",
    port: int = 8080,
    debug: bool = False,
    config: Optional[Config] = None
) -> None:
    """
    Run the web application server.
    
    Args:
        host: Host address to bind
        port: Port to listen on
        debug: Enable debug mode
        config: Application configuration
    """
    if config is None:
        config = load_config()
    
    app = create_app(config=config, debug=debug)
    
    logger.info(f"Starting web server on {host}:{port}")
    
    import uvicorn
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info"
    )
