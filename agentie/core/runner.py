import os
import threading
import time

from agents import Runner
from agents.mcp import MCPServerStreamableHttp

from agentie.agents.assistant import build_assistant
from agentie.core.agent_prompt import agent_from_session,build_agent_instructions
from agentie.core.agent_teams import team_context
from agentie.core.memory_store import add_message,build_context_prompt,set_context
from agentie.core.model_routing import choose_model_route,should_escalate_local_error
from agentie.core.npc_brain import try_npc_response
from agentie.core.observability import current_trace_id,finish_trace,record_event,record_model_error,record_model_result,start_trace
from agentie.core.role_store import resolve_role
from agentie.core.workflow_skills import instruction_block,matching_workflow_skills
from agentie.models.provider import get_provider_info

_PROVIDER_COOLDOWNS:dict[str,dict]={};_PROVIDER_COOLDOWN_LOCK=threading.Lock()


class _ProviderCooldownError(RuntimeError):
    """Internal signal that a provider call was intentionally suppressed."""


def _provider_key(info:dict)->str:return f"{info.get('provider','provider')}:{info.get('model','model')}".casefold()
def provider_cooldown(info:dict|None=None)->dict|None:
    current=info or get_provider_info();key=_provider_key(current);now=time.time()
    with _PROVIDER_COOLDOWN_LOCK:
        item=_PROVIDER_COOLDOWNS.get(key)
        if not item:return None
        if float(item.get("until") or 0)<=now:_PROVIDER_COOLDOWNS.pop(key,None);return None
        return dict(item)
def _start_provider_cooldown(info:dict,message:str)->dict:
    seconds=max(15,min(int(os.getenv("AGENTIE_PROVIDER_COOLDOWN_SECONDS","90")),900));item={"provider":info.get("provider"),"model":info.get("model"),"message":message,"started_at":time.time(),"until":time.time()+seconds,"seconds":seconds}
    with _PROVIDER_COOLDOWN_LOCK:_PROVIDER_COOLDOWNS[_provider_key(info)]=item
    return dict(item)
def _friendly_provider_error(exc:Exception)->str|None:
    text=str(exc or "");lower=text.lower()
    if "429" in lower or "resource_exhausted" in lower or "quota exceeded" in lower or "rate limit" in lower or "usage limit" in lower:return "The AI model is temporarily at its usage limit. Please try again shortly."
    if "402" in lower or "requires more credits" in lower or "insufficient" in lower and "credit" in lower:return "The AI provider is out of credits right now. Add credits or switch providers to continue."
    if "404" in lower and ("model" in lower or "not found" in lower):return "The configured AI model is unavailable. Please update the model setting and try again."
    if "timeout" in lower or "timed out" in lower:return "The AI provider took too long to respond. Please try again."
    if "connection refused" in lower or "failed to connect" in lower or "connecterror" in lower:return "The selected AI model runtime is not reachable right now."
    return None


def _cooldown_error(info:dict)->RuntimeError|None:
    cooldown=provider_cooldown(info)
    if not cooldown:return None
    remaining=max(1,int(float(cooldown.get("until") or 0)-time.time()));friendly=str(cooldown.get("message") or "The AI model is temporarily at its usage limit. Please try again shortly.")
    record_event("provider_cooldown",info.get("provider") or "provider",metadata={"model":info.get("model"),"remaining_seconds":remaining,"provider_calls":0})
    return _ProviderCooldownError(f"{friendly} Agentie is temporarily suppressing repeated provider calls for about {remaining} more second(s).")


def _npc_shortcuts_allowed(session_id:str|None)->bool:
    """NPC shortcuts are only for real user-facing conversation sessions.

    Team/group collaboration uses internal ``handoff:`` sessions containing
    orchestration instructions. Feeding those generated prompts to the NPC
    preference learner can mistake internal wording for a user preference and
    return an acknowledgement instead of actually doing/replying to the work.
    """
    value=str(session_id or "")
    return not (value.startswith("handoff:") or ":handoff:" in value)


async def _invoke_provider(provider_info:dict,agent_type:str,effective_message:str,role_info:dict,persistent_instructions:str|None,persistent_agent:dict|None):
    mcp_url=os.getenv("AGENTIE_MCP_URL","").strip()
    if mcp_url and (persistent_agent or str(role_info.get("base")) in {"general","manager"}):
        headers={};token=os.getenv("AGENTIE_MCP_TOKEN","").strip()
        if token:headers["Authorization"]=f"Bearer {token}"
        record_event("mcp","connect",metadata={"url":mcp_url})
        async with MCPServerStreamableHttp(name="Agentie MCP",params={"url":mcp_url,"headers":headers},cache_tools_list=True) as server:
            assistant=build_assistant(agent_type,mcp_servers=[server],role_info=role_info,persistent_instructions=persistent_instructions,persistent_agent=persistent_agent,provider_info=provider_info);return await Runner.run(assistant,effective_message)
    assistant=build_assistant(agent_type,role_info=role_info,persistent_instructions=persistent_instructions,persistent_agent=persistent_agent,provider_info=provider_info);return await Runner.run(assistant,effective_message)


async def _attempt(provider_info:dict,agent_type:str,effective_message:str,role_info:dict,persistent_instructions:str|None,persistent_agent:dict|None,trace_id:str):
    blocked=_cooldown_error(provider_info)
    if blocked:raise blocked
    model_name=str(provider_info.get("model") or "model");record_event("provider",str(provider_info.get("provider") or "provider"),metadata={"model":model_name,"tier":provider_info.get("tier")});started=time.perf_counter()
    try:
        result=await _invoke_provider(provider_info,agent_type,effective_message,role_info,persistent_instructions,persistent_agent);latency_ms=(time.perf_counter()-started)*1000;record_model_result(result,model_name,latency_ms,trace_id);return str(result.final_output)
    except Exception as exc:
        latency_ms=(time.perf_counter()-started)*1000;record_model_error(model_name,exc,latency_ms,trace_id);raise


async def run_agent(message:str,agent_type:str="general",session_id:str|None=None)->str:
    """Run one turn through Agentie's Local / Auto / Powerful model router."""
    own_trace=False;trace_id=current_trace_id()
    if not trace_id:trace_id=start_trace(session_id,agent_type,message);own_trace=True
    original_message=message;persistent_agent=agent_from_session(session_id);persistent_instructions=None
    if persistent_agent:
        npc=None
        if _npc_shortcuts_allowed(session_id):
            npc=try_npc_response(persistent_agent,message,session_id=session_id)
        else:
            record_event("npc_bypass","internal_handoff",metadata={"session_id":session_id,"provider_calls":0})
        if npc is not None and npc.get("message") is not None:
            output=str(npc.get("message") or "")
            if session_id:add_message(session_id,"user",original_message,{"agent_type":"persistent","routed_by":"npc_brain","npc_confidence":npc.get("confidence")});add_message(session_id,"assistant",output,{"agent_type":"persistent","routed_by":"npc_brain","npc_confidence":npc.get("confidence")})
            record_event("npc_brain",str(persistent_agent.get("name") or "agent"),metadata={"session_id":session_id,"provider_calls":0,"confidence":npc.get("confidence")})
            if own_trace:finish_trace(trace_id,"completed")
            return output
        if npc is not None and npc.get("escalate_message"):message=str(npc["escalate_message"]);record_event("npc_context",str(persistent_agent.get("name") or "agent"),metadata={"session_id":session_id,"provider_calls":0})
        persistent_instructions=build_agent_instructions(persistent_agent)
        teams=team_context(persistent_agent)
        if teams:persistent_instructions += "\n\nUSER-CREATED TEAM CONTEXT:\n"+teams
        matched=matching_workflow_skills(original_message,persistent_agent,3)
        if matched:persistent_instructions += "\n\nRelevant active reusable skills for this request:\n\n"+"\n\n---\n\n".join(instruction_block(item) for item in matched)
    effective_message=build_context_prompt(session_id,message) if session_id else message
    role_info={"name":str(persistent_agent.get("name") or "agent"),"base":"general","instruction":f"Configured job ownership: {persistent_agent.get('role') or 'general ownership'}"} if persistent_agent else resolve_role(agent_type)
    route=choose_model_route(original_message);provider_info=get_provider_info("local") if route.get("tier")=="local" else get_provider_info();model_name=provider_info["model"]
    if session_id:add_message(session_id,"user",original_message,{"agent_type":"persistent" if persistent_agent else agent_type,"runtime_role":role_info.get("name"),"model_mode":route.get("mode"),"model_tier":route.get("tier")})
    record_event("agent",str(role_info.get("name") or agent_type),metadata={"base":"persistent" if persistent_agent else role_info.get("base"),"session_id":session_id});record_event("model_route",str(route.get("tier") or "powerful"),metadata={"mode":route.get("mode"),"reason":route.get("reason"),"model":model_name,"local_available":route.get("local_available"),"cloud_configured":route.get("cloud_configured"),"score":(route.get("task") or {}).get("score"),"signals":(route.get("task") or {}).get("reasons",[])})
    failed_info=provider_info
    try:
        try:
            output=await _attempt(provider_info,agent_type,effective_message,role_info,persistent_instructions,persistent_agent,trace_id)
        except Exception as first_exc:
            if route.get("tier")=="local" and route.get("allow_cloud_fallback") and should_escalate_local_error(first_exc):
                powerful=get_provider_info();failed_info=powerful;record_event("model_escalation","powerful",metadata={"from_model":provider_info.get("model"),"to_model":powerful.get("model"),"reason":str(first_exc)[:240],"mode":route.get("mode")});output=await _attempt(powerful,agent_type,effective_message,role_info,persistent_instructions,persistent_agent,trace_id);provider_info=powerful;model_name=str(powerful.get("model") or model_name)
            else:
                raise
        if session_id:add_message(session_id,"assistant",output,{"agent_type":"persistent" if persistent_agent else agent_type,"runtime_role":role_info.get("name"),"model_mode":route.get("mode"),"model_tier":provider_info.get("tier"),"model":provider_info.get("model")});set_context(session_id,"last_provider_failure",None)
        if own_trace:finish_trace(trace_id,"completed")
        return output
    except Exception as exc:
        # A cooldown is a deliberate "do not call the provider" decision. Preserve
        # its suppression message and do not accidentally restart/extend the cooldown.
        if isinstance(exc,_ProviderCooldownError):
            if session_id:set_context(session_id,"last_provider_failure",{"user_message":original_message,"error":str(exc),"model":failed_info.get("model"),"trace_id":trace_id,"model_mode":route.get("mode"),"model_tier":failed_info.get("tier"),"cooldown":True})
            if own_trace:finish_trace(trace_id,"failed",str(exc))
            raise
        friendly=_friendly_provider_error(exc)
        if friendly and "usage limit" in friendly.casefold() and str(failed_info.get("provider"))!="local":cooldown=_start_provider_cooldown(failed_info,friendly);record_event("provider_cooldown_started",failed_info.get("provider") or "provider",metadata={"model":failed_info.get("model"),"seconds":cooldown.get("seconds"),"provider_calls":0})
        if session_id:set_context(session_id,"last_provider_failure",{"user_message":original_message,"error":friendly or str(exc),"model":failed_info.get("model"),"trace_id":trace_id,"model_mode":route.get("mode"),"model_tier":failed_info.get("tier")})
        if own_trace:finish_trace(trace_id,"failed",str(exc))
        if route.get("mode")=="local" and str(failed_info.get("provider"))=="local" and friendly:
            raise RuntimeError(f"{friendly} Local mode will not send this task to a cloud model.") from exc
        if friendly:raise RuntimeError(friendly) from exc
        raise
