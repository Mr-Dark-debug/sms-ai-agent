"""
Web Routes - API endpoints and page routes
=========================================

This module defines all web routes for the SMS AI Agent interface.
"""

from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from core.logging import get_logger
from core.exceptions import SMSAgentError

logger = get_logger("web.routes")

router = APIRouter()


# === Page Routes ===

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard page."""
    templates = request.app.state.templates
    database = request.app.state.database
    config = request.app.state.config
    sms_handler = request.app.state.sms_handler
    ai_responder = request.app.state.ai_responder
    
    # Get statistics
    stats = database.get_statistics()
    
    # Get recent messages
    recent_messages = database.get_messages(limit=10)
    
    # Check LLM status
    llm_status = ai_responder.test_connection() if ai_responder.llm else {"llm_available": False}
    
    # Check SMS status
    sms_available = sms_handler.is_available
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "stats": stats,
            "recent_messages": recent_messages,
            "llm_status": llm_status,
            "sms_available": sms_available,
            "config": config,
            "page": "dashboard"
        }
    )


@router.get("/messages", response_class=HTMLResponse)
async def messages_page(
    request: Request,
    phone: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """Render the messages log page."""
    templates = request.app.state.templates
    database = request.app.state.database
    
    messages = database.get_messages(
        phone_number=phone,
        direction=direction,
        limit=limit,
        offset=offset
    )
    
    return templates.TemplateResponse(
        "messages.html",
        {
            "request": request,
            "messages": messages,
            "filters": {"phone": phone, "direction": direction},
            "limit": limit,
            "offset": offset,
            "page": "messages"
        }
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render the settings page."""
    templates = request.app.state.templates
    config = request.app.state.config
    security = request.app.state.security
    ai_responder = request.app.state.ai_responder
    
    # Get API key status
    api_keys = {
        "openrouter": security.has_api_key("openrouter"),
        "ollama": security.has_api_key("ollama"),
    }
    
    # Get available models
    models = []
    if ai_responder.llm:
        try:
            models = ai_responder.llm.get_models()
        except Exception:
            pass
    
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "config": config,
            "api_keys": api_keys,
            "models": models[:20],  # Limit to 20 for UI
            "page": "settings"
        }
    )


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    """Render the rules editor page."""
    templates = request.app.state.templates
    rules_engine = request.app.state.rules_engine
    
    rules = rules_engine.get_all_rules()
    
    return templates.TemplateResponse(
        "rules.html",
        {
            "request": request,
            "rules": rules,
            "page": "rules"
        }
    )


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    log_type: str = Query("llm", pattern="^(llm|guardrail)$"),
    limit: int = Query(100, ge=1, le=500)
):
    """Render the logs viewer page."""
    templates = request.app.state.templates
    database = request.app.state.database
    
    if log_type == "llm":
        logs = database.get_llm_logs(limit=limit)
    else:
        logs = database.get_guardrail_logs(limit=limit)
    
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "logs": logs,
            "log_type": log_type,
            "page": "logs"
        }
    )


@router.get("/test", response_class=HTMLResponse)
async def test_page(request: Request):
    """Render the test message simulator page."""
    templates = request.app.state.templates
    rules_engine = request.app.state.rules_engine
    
    rules = rules_engine.get_all_rules()
    
    return templates.TemplateResponse(
        "test.html",
        {
            "request": request,
            "rules": rules,
            "page": "test"
        }
    )


@router.get("/personality", response_class=HTMLResponse)
async def personality_page(request: Request):
    """Render the personality editor page."""
    templates = request.app.state.templates
    config = request.app.state.config
    ai_responder = request.app.state.ai_responder
    
    return templates.TemplateResponse(
        "personality.html",
        {
            "request": request,
            "config": config,
            "personality": ai_responder.personality,
            "agent_rules": ai_responder.agent_rules,
            "page": "personality"
        }
    )


# === API Routes ===

class SettingsUpdate(BaseModel):
    """Settings update model."""
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_temperature: Optional[float] = None
    llm_max_tokens: Optional[int] = None
    sms_auto_reply: Optional[bool] = None
    sms_ai_mode: Optional[bool] = None
    guardrail_max_length: Optional[int] = None


class APIKeyUpdate(BaseModel):
    """API key update model."""
    provider: str
    api_key: str


class RuleCreate(BaseModel):
    """Rule creation model."""
    name: str
    patterns: List[str]
    match_type: str = "contains"
    responses: List[str]
    priority: int = 50
    enabled: bool = True


class TestMessage(BaseModel):
    """Test message model."""
    message: str
    phone_number: Optional[str] = "+1234567890"
    use_ai: bool = False


@router.post("/api/settings")
async def update_settings(request: Request, settings: SettingsUpdate):
    """Update application settings."""
    config = request.app.state.config
    database = request.app.state.database
    
    try:
        if settings.llm_provider is not None:
            config.llm.provider = settings.llm_provider
            database.set_setting("llm_provider", settings.llm_provider)
        
        if settings.llm_model is not None:
            config.llm.model = settings.llm_model
            database.set_setting("llm_model", settings.llm_model)
        
        if settings.llm_temperature is not None:
            config.llm.temperature = settings.llm_temperature
            database.set_setting("llm_temperature", settings.llm_temperature)
        
        if settings.llm_max_tokens is not None:
            config.llm.max_tokens = settings.llm_max_tokens
            database.set_setting("llm_max_tokens", settings.llm_max_tokens)
        
        if settings.sms_auto_reply is not None:
            config.sms.auto_reply_enabled = settings.sms_auto_reply
            database.set_setting("sms_auto_reply", settings.sms_auto_reply)
        
        if settings.sms_ai_mode is not None:
            config.sms.ai_mode_enabled = settings.sms_ai_mode
            database.set_setting("sms_ai_mode", settings.sms_ai_mode)
        
        if settings.guardrail_max_length is not None:
            config.guardrail.max_response_length = settings.guardrail_max_length
            database.set_setting("guardrail_max_length", settings.guardrail_max_length)
        
        return {"success": True, "message": "Settings updated"}
    
    except Exception as e:
        logger.error(f"Failed to update settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/api-key")
async def update_api_key(request: Request, key_data: APIKeyUpdate):
    """Update API key for a provider."""
    security = request.app.state.security
    config = request.app.state.config
    
    try:
        if not security.validate_api_key(key_data.provider, key_data.api_key):
            raise HTTPException(status_code=400, detail="Invalid API key format")
        
        security.store_api_key(key_data.provider, key_data.api_key)
        
        # Update config
        config.llm.api_key = key_data.api_key
        
        # Reinitialize LLM if needed
        if key_data.provider == config.llm.provider:
            from llm.factory import create_llm_provider
            request.app.state.ai_responder.llm = create_llm_provider(config=config)
        
        return {"success": True, "message": f"API key stored for {key_data.provider}"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to store API key: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/rules")
async def create_rule(request: Request, rule_data: RuleCreate):
    """Create a new rule."""
    rules_engine = request.app.state.rules_engine
    
    try:
        from rules.engine import Rule, MatchType
        
        rule = Rule(
            name=rule_data.name,
            patterns=rule_data.patterns,
            match_type=MatchType(rule_data.match_type),
            responses=rule_data.responses,
            priority=rule_data.priority,
            enabled=rule_data.enabled
        )
        
        rules_engine.add_rule(rule)
        rules_engine.save_rules()
        
        return {"success": True, "message": f"Rule '{rule_data.name}' created"}
    
    except Exception as e:
        logger.error(f"Failed to create rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/rules/{rule_name}")
async def delete_rule(request: Request, rule_name: str):
    """Delete a rule."""
    rules_engine = request.app.state.rules_engine
    
    try:
        if rules_engine.remove_rule(rule_name):
            rules_engine.save_rules()
            return {"success": True, "message": f"Rule '{rule_name}' deleted"}
        else:
            raise HTTPException(status_code=404, detail="Rule not found")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/test-message")
async def test_message(request: Request, test_data: TestMessage):
    """Test message response generation."""
    ai_responder = request.app.state.ai_responder
    guardrails = request.app.state.guardrails
    rules_engine = request.app.state.rules_engine
    
    try:
        # Check if AI should be used
        original_use_ai = ai_responder.config.sms.ai_mode_enabled
        ai_responder.config.sms.ai_mode_enabled = test_data.use_ai
        
        # Generate response
        result = ai_responder.respond(
            incoming_message=test_data.message,
            phone_number=test_data.phone_number
        )
        
        # Restore original setting
        ai_responder.config.sms.ai_mode_enabled = original_use_ai
        
        # Get rule match if applicable
        rule_match = rules_engine.match(test_data.message)
        
        return {
            "success": True,
            "response": result.response,
            "source": result.source,
            "model": result.model,
            "tokens_used": result.tokens_used,
            "latency_ms": result.latency_ms,
            "guardrail_violations": result.guardrail_result.violations if result.guardrail_result else [],
            "matched_rule": rule_match.rule.name if rule_match else None,
        }
    
    except Exception as e:
        logger.error(f"Test message failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/personality")
async def update_personality(request: Request):
    """Update personality and agent instructions."""
    form = await request.form()
    ai_responder = request.app.state.ai_responder
    config = request.app.state.config
    
    try:
        personality = form.get("personality", "")
        agent_rules = form.get("agent_rules", "")
        
        # Update in memory
        ai_responder.update_personality(personality)
        ai_responder.update_agent_rules(agent_rules)
        
        # Save to files
        personality_path = Path(config.config_dir) / "personality.md"
        agent_path = Path(config.config_dir) / "agent.md"
        
        with open(personality_path, "w") as f:
            f.write(personality)
        
        with open(agent_path, "w") as f:
            f.write(agent_rules)
        
        return {"success": True, "message": "Instructions updated"}
    
    except Exception as e:
        logger.error(f"Failed to update personality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/status")
async def get_status(request: Request):
    """Get system status."""
    database = request.app.state.database
    sms_handler = request.app.state.sms_handler
    ai_responder = request.app.state.ai_responder
    guardrails = request.app.state.guardrails
    
    stats = database.get_statistics()
    llm_status = ai_responder.test_connection() if ai_responder.llm else {"llm_available": False}
    guardrail_status = guardrails.get_status()
    
    return {
        "database": stats,
        "sms": {"available": sms_handler.is_available},
        "llm": llm_status,
        "guardrails": guardrail_status,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/api/models")
async def get_models(request: Request):
    """Get available LLM models."""
    ai_responder = request.app.state.ai_responder
    
    if not ai_responder.llm:
        return {"models": []}
    
    try:
        models = ai_responder.llm.get_models()
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}


class SendSMSRequest(BaseModel):
    """Send SMS request model."""
    phone_number: str
    message: str


@router.post("/api/send-sms")
async def send_sms(request: Request, sms_data: SendSMSRequest):
    """Send an SMS message."""
    sms_handler = request.app.state.sms_handler
    
    if not sms_handler.is_available:
        raise HTTPException(status_code=503, detail="SMS not available. Check Termux:API installation.")
    
    try:
        success = sms_handler.send_sms(
            phone_number=sms_data.phone_number,
            message=sms_data.message
        )
        
        if success:
            return {"success": True, "message": "SMS sent successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send SMS")
    
    except Exception as e:
        logger.error(f"Failed to send SMS: {e}")
        raise HTTPException(status_code=500, detail=str(e))
