import chainlit as cl
import httpx
import json
import os
from typing import Dict, Any, List
import asyncio
import uuid

# 환경 변수 설정
CHAT_GATEWAY_URL = os.environ.get("CHAT_GATEWAY_URL", "http://chat-gateway:8002")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor:8003")
TOOL_REGISTRY_URL = os.environ.get("TOOL_REGISTRY_URL", "http://tool-registry:8005")
EVENT_GATEWAY_URL = os.environ.get("EVENT_GATEWAY_URL", "http://event-gateway:8001")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:8004")

# 서비스 상태 저장용 전역 변수
service_status = {}
available_tools = {}

@cl.on_chat_start
async def start():
    """채팅 시작 시 호출되는 함수"""
    # 세션 ID 생성
    session_id = str(uuid.uuid4())
    
    # 초기 메시지 전송
    await cl.Message(content="안녕하세요! 서비스입니다. 어떤 도움이 필요하신가요?", author="시스템").send()
    
    # 시스템 상태 확인 및 표시
    system_status = await check_system_status()
    tools = await get_available_tools()
    
    # 시스템 상태 요약 표 생성
    status_md = "## 시스템 상태\n\n"
    status_md += "| 서비스 | 상태 |\n"
    status_md += "| ------ | ---- |\n"
    
    for service, status in system_status.items():
        status_icon = "✅" if status else "❌"
        status_md += f"| {service} | {status_icon} |\n"
    
    # 시스템 상태 메시지 전송
    await cl.Message(content=status_md, author="시스템").send()
    
    # 사용 가능한 도구 목록 표시
    if tools:
        tools_md = "## 사용 가능한 도구\n\n"
        tools_md += "| 도구 ID | 이름 | 설명 |\n"
        tools_md += "| ------- | ---- | ---- |\n"
        
        for tool in tools:
            tools_md += f"| {tool.get('tool_id', 'N/A')} | {tool.get('name', 'N/A')} | {tool.get('description', 'N/A')} |\n"
        
        # 도구 목록 메시지 전송
        await cl.Message(content=tools_md, author="시스템").send()

@cl.on_message
async def main(message: cl.Message):
    """사용자 메시지 처리"""
    try:
        # 메시지 처리 중 표시
        processing_msg = await cl.Message(content="메시지를 처리 중입니다...", author="시스템").send()
        
        if message.content.startswith("/"):
            # 명령어 처리
            await handle_command(message.content, processing_msg)
        else:
            # 일반 메시지는 채팅 게이트웨이로 전송
            await send_to_chat_gateway(message.content, processing_msg)
            
    except Exception as e:
        await cl.Message(content=f"오류가 발생했습니다: {str(e)}", author="시스템").send()

async def check_system_status() -> Dict[str, bool]:
    """각 MSA 컴포넌트의 상태를 확인"""
    services = {
        "채팅 게이트웨이": f"{CHAT_GATEWAY_URL}/health",
        "수퍼바이저": f"{SUPERVISOR_URL}/health",
        "도구 레지스트리": f"{TOOL_REGISTRY_URL}/health", 
        "이벤트 게이트웨이": f"{EVENT_GATEWAY_URL}/health",
        "MCP 서버": f"{MCP_SERVER_URL}/health"
    }
    
    results = {}
    
    async with httpx.AsyncClient(timeout=2.0) as client:
        for service_name, url in services.items():
            try:
                response = await client.get(url)
                results[service_name] = response.status_code == 200
            except Exception:
                results[service_name] = False
    
    global service_status
    service_status = results
    
    return results

async def get_available_tools() -> List[Dict[str, Any]]:
    """도구 레지스트리에서 사용 가능한 도구 목록 가져오기"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{TOOL_REGISTRY_URL}/tools")
            
            if response.status_code == 200:
                tools = response.json()
                global available_tools
                available_tools = tools
                return tools
            return []
    except Exception:
        return []

async def handle_command(command: str, processing_msg: cl.Message):
    """특별 명령어 처리"""
    cmd_parts = command.split()
    cmd = cmd_parts[0].lower()
    
    if cmd == "/상태":
        # 시스템 상태 확인
        status = await check_system_status()
        status_msg = "## 시스템 상태\n\n"
        
        for service, is_healthy in status.items():
            status_icon = "✅" if is_healthy else "❌"
            status_msg += f"**{service}**: {status_icon}\n"
        
        # 기존 메시지 삭제 후 새 메시지 전송
        await processing_msg.remove()
        await cl.Message(content=status_msg, author="시스템").send()
        
    elif cmd == "/도구":
        # 사용 가능한 도구 목록 표시
        tools = await get_available_tools()
        
        if not tools:
            await processing_msg.remove()
            await cl.Message(content="도구 정보를 가져올 수 없습니다.", author="시스템").send()
            return
            
        tools_msg = "## 사용 가능한 도구\n\n"
        
        for tool in tools:
            tools_msg += f"**{tool.get('name', 'N/A')}** (`{tool.get('tool_id', 'N/A')}`)\n"
            tools_msg += f"- {tool.get('description', '설명 없음')}\n\n"
        
        # 기존 메시지 삭제 후 새 메시지 전송
        await processing_msg.remove()
        await cl.Message(content=tools_msg, author="시스템").send()
        
    elif cmd == "/도구실행" and len(cmd_parts) > 1:
        # 특정 도구 실행
        tool_id = cmd_parts[1]
        
        # 도구 파라미터 파싱 (예: /도구실행 tool_id param1=value1 param2=value2)
        params = {}
        if len(cmd_parts) > 2:
            for param in cmd_parts[2:]:
                if "=" in param:
                    key, value = param.split("=", 1)
                    params[key] = value
        
        await execute_tool(tool_id, params, processing_msg)
        
    elif cmd == "/도움말":
        # 도움말 표시
        help_msg = """## 사용 가능한 명령어

- **/상태**: 모든 서비스의 현재 상태를 확인합니다.
- **/도구**: 사용 가능한 도구 목록을 표시합니다.
- **/도구실행 [도구ID] [파라미터]**: 지정된 도구를 실행합니다.
  예: `/도구실행 car_diagnostic_tool diagnostic_data={"car_model":"소나타"}`
- **/도움말**: 이 도움말 메시지를 표시합니다.
"""
        # 기존 메시지 삭제 후 새 메시지 전송
        await processing_msg.remove()
        await cl.Message(content=help_msg, author="시스템").send()
    else:
        # 기존 메시지 삭제 후 새 메시지 전송
        await processing_msg.remove()
        await cl.Message(content="알 수 없는 명령어입니다. '/도움말'을 입력하여 사용 가능한 명령어를 확인하세요.", author="시스템").send()

async def execute_tool(tool_id: str, params: Dict[str, str], processing_msg: cl.Message):
    """특정 도구 실행"""
    try:
        # 실행 중 메시지 업데이트
        await processing_msg.remove()
        status_msg = await cl.Message(content=f"도구 '{tool_id}'를 실행 중입니다...", author="시스템").send()
        
        # MCP 서버로 도구 실행 요청 전송
        async with httpx.AsyncClient() as client:
            payload = {
                "tool_name": tool_id,
                "parameters": params,
                "context": {}
            }
            
            response = await client.post(f"{MCP_SERVER_URL}/execute", json=payload)
            
            if response.status_code == 200:
                result = response.json()
                execution_id = result.get("execution_id")
                
                # 실행 상태 확인
                await asyncio.sleep(2)
                status_response = await client.get(f"{MCP_SERVER_URL}/status/{execution_id}")
                
                if status_response.status_code == 200:
                    execution_status = status_response.json()
                    if execution_status.get("status") == "completed":
                        result_content = f"### 도구 실행 결과\n\n```json\n{json.dumps(execution_status.get('result', {}), indent=2, ensure_ascii=False)}\n```"
                        await status_msg.remove()
                        await cl.Message(content=result_content, author="시스템").send()
                    else:
                        status_content = f"도구 실행 중입니다. 상태: {execution_status.get('status')}"
                        await status_msg.remove()
                        await cl.Message(content=status_content, author="시스템").send()
                else:
                    error_content = f"도구 실행 상태 확인 실패. 상태 코드: {status_response.status_code}"
                    await status_msg.remove()
                    await cl.Message(content=error_content, author="시스템").send()
            else:
                error_content = f"도구 실행 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                await status_msg.remove()
                await cl.Message(content=error_content, author="시스템").send()
                
    except Exception as e:
        error_content = f"도구 실행 중 오류가 발생했습니다: {str(e)}"
        await status_msg.remove()
        await cl.Message(content=error_content, author="시스템").send()

async def send_to_chat_gateway(message_content: str, processing_msg: cl.Message):
    """메시지를 채팅 게이트웨이로 전송"""
    try:
        # 무작위 클라이언트 ID 생성
        client_id = f"cl_{id(message_content)}"
        
        async with httpx.AsyncClient() as client:
            payload = {
                "client_id": client_id,
                "message": message_content,
                "message_type": "chat"
            }
            
            response = await client.post(f"{CHAT_GATEWAY_URL}/messages", json=payload)
            
            if response.status_code == 200:
                # 실시간 업데이트를 위한 웹소켓 연결 대신, 수퍼바이저에서 바로 응답 확인
                await asyncio.sleep(2)
                
                # 수퍼바이저에서 응답 확인 시도
                try:
                    supervisor_response = await client.get(f"{SUPERVISOR_URL}/responses/{client_id}")
                    if supervisor_response.status_code == 200:
                        response_data = supervisor_response.json()
                        response_content = response_data.get("message", "처리가 완료되었습니다.")
                        await processing_msg.remove()
                        await cl.Message(content=response_content, author="시스템").send()
                    else:
                        # 응답을 받지 못했을 경우 기본 응답
                        await processing_msg.remove()
                        await cl.Message(content="메시지를 처리했습니다. 자세한 응답을 준비 중입니다.", author="시스템").send()
                except Exception:
                    await processing_msg.remove()
                    await cl.Message(content="메시지가 전송되었습니다. 곧 응답이 도착할 예정입니다.", author="시스템").send()
            else:
                error_content = f"메시지 전송 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                await processing_msg.remove()
                await cl.Message(content=error_content, author="시스템").send()
    except Exception as e:
        error_content = f"메시지 전송 중 오류가 발생했습니다: {str(e)}"
        await processing_msg.remove()
        await cl.Message(content=error_content, author="시스템").send() 