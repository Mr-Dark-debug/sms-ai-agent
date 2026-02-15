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
        timeout=config.sms.sms_timeout,
        webhook_config={
            "enabled": config.sms.webhook_enabled,
            "url": config.sms.webhook_url,
            "headers": config.sms.webhook_headers
        }
    )
    
    ai_responder = AIResponder(
        config=config,
        database=database,
        guardrails=guardrails,
        rules_engine=rules_engine,
        personality_path=os.path.join(config.config_dir, "personality.md"),
        agent_path=os.path.join(config.config_dir, "agent.md")
    )

    # Start SMS listener with callback
    from core.rate_limiter import RateLimiter
    rate_limiter = RateLimiter(
        max_per_minute=config.rate_limit.max_messages_per_minute,
        max_per_recipient_per_hour=config.rate_limit.max_per_recipient_per_hour,
        max_per_recipient_per_day=config.rate_limit.max_per_recipient_per_day
    )

    def handle_incoming_sms(msg):
        logger.info(f"Web listener: Received message from {msg.phone_number}")
        
        # Check if number is replyable (numeric)
        if not sms_handler.is_replyable_number(msg.phone_number):
            logger.info(f"Web listener: Ignoring non-replyable sender {msg.phone_number}")
            return

        # Clean the message content
        content = msg.message.strip()
        if content.startswith("Sent:"):
            content = content[5:].strip()
        elif content.startswith("Delivered:"):
            content = content[10:].strip()
            
        if not content:
            logger.info("Web listener: Message empty after cleaning, skipping.")
            return

        # Check if we already responded to this exact message content (idempotency)
        if database.was_message_responded(msg.phone_number, content):
            logger.info(f"Web listener: Already responded to this message from {msg.phone_number}, skipping.")
            return

        # Check if message is an echo of our own last message
        last_msgs = database.get_messages(phone_number=msg.phone_number, limit=1)
        if last_msgs and last_msgs[0]['direction'] == 'outgoing' and last_msgs[0]['message'] == content:
            logger.info(f"Web listener: Detected echo of our own message, skipping.")
            return

        # Check rate limit
        result = rate_limiter.check_and_record(msg.phone_number)
        if not result.allowed:
            logger.warning(f"Rate limited: {msg.phone_number}")
            return
        
        # Store incoming message
        msg_id = database.add_message(
            direction="incoming",
            phone_number=msg.phone_number,
            message=content,
            status="delivered"
        )
        
        # Check if auto-reply is enabled
        if not config.sms.auto_reply_enabled:
            return
        
        # Generate response
        response = ai_responder.respond(content, msg.phone_number)
        
        if response.response:
            logger.info(f"Web listener: AI generated response for {msg.phone_number}: '{response.response[:30]}...'")
            # Send response
            try:
                logger.info(f"Web listener: Attempting to send SMS to {msg.phone_number}")
                sms_handler.send_sms(msg.phone_number, response.response)
                database.add_message(
                    direction="outgoing",
                    phone_number=msg.phone_number,
                    message=response.response,
                    status="sent",
                    response_to=msg_id
                )
                logger.info(f"Web listener: Successfully sent response to {msg.phone_number}")
            except Exception as e:
                logger.error(f"Web listener: Failed to send response to {msg.phone_number}: {e}", exc_info=True)
        else:
            logger.warning(f"Web listener: AI produced empty response for {msg.phone_number}")

    sms_handler.on_message_received(handle_incoming_sms)
    sms_handler.start_listener(poll_interval=3)
    
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
