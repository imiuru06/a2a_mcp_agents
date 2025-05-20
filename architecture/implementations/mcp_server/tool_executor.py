#!/usr/bin/env python3
"""
MCP Server - 도구 실행 모듈

이 모듈은 도구 실행 요청을 처리하고 Docker 컨테이너를 통해 도구를 실행합니다.
"""

import os
import json
import uuid
import time
import asyncio
import logging
from typing import Dict, Any, Optional, List, Union, Callable
from datetime import datetime

import docker
from docker.errors import DockerException, ImageNotFound, APIError

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("tool_executor")


class ToolExecutionError(Exception):
    """도구 실행 중 발생하는 예외"""
    pass


class ToolExecutor:
    """도구 실행 관리자"""
    
    def __init__(
        self,
        docker_client: Optional[docker.DockerClient] = None,
        tool_registry_url: Optional[str] = None,
        container_network: str = "mcp-tools",
        execution_timeout: int = 300,
        max_retries: int = 3
    ):
        """
        Args:
            docker_client: Docker 클라이언트 (None인 경우 자동 생성)
            tool_registry_url: 도구 레지스트리 URL
            container_network: 컨테이너 네트워크 이름
            execution_timeout: 실행 제한 시간(초)
            max_retries: 최대 재시도 횟수
        """
        self.docker_client = docker_client or docker.from_env()
        self.tool_registry_url = tool_registry_url
        self.container_network = container_network
        self.execution_timeout = execution_timeout
        self.max_retries = max_retries
        
        # 실행 중인 작업 저장소
        self.running_tasks: Dict[str, Dict[str, Any]] = {}
        
        # 취소 토큰 저장소
        self.cancellation_tokens: Dict[str, asyncio.Event] = {}
        
        # 컨테이너 네트워크 확인 및 생성
        self._ensure_network()
    
    def _ensure_network(self) -> None:
        """컨테이너 네트워크 확인 및 생성"""
        try:
            networks = self.docker_client.networks.list(names=[self.container_network])
            if not networks:
                logger.info(f"네트워크 '{self.container_network}' 생성 중...")
                self.docker_client.networks.create(
                    name=self.container_network,
                    driver="bridge",
                    check_duplicate=True
                )
                logger.info(f"네트워크 '{self.container_network}' 생성 완료")
            else:
                logger.info(f"네트워크 '{self.container_network}' 이미 존재함")
        except DockerException as e:
            logger.error(f"Docker 네트워크 확인 중 오류 발생: {str(e)}")
            raise ToolExecutionError(f"Docker 네트워크 확인 실패: {str(e)}")
    
    async def execute_tool(
        self,
        tool_name: str,
        tool_version: Optional[str],
        parameters: Dict[str, Any],
        run_id: Optional[str] = None,
        context_id: Optional[str] = None,
        timeout: Optional[int] = None,
        callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        도구 실행
        
        Args:
            tool_name: 도구 이름
            tool_version: 도구 버전 (None인 경우 최신 버전)
            parameters: 도구 매개변수
            run_id: 실행 ID (None인 경우 자동 생성)
            context_id: 컨텍스트 ID
            timeout: 실행 제한 시간(초) (None인 경우 기본값 사용)
            callback: 상태 업데이트 콜백 함수
            
        Returns:
            Dict[str, Any]: 실행 결과
            
        Raises:
            ToolExecutionError: 도구 실행 중 오류 발생
        """
        # 실행 ID 생성 또는 사용
        run_id = run_id or str(uuid.uuid4())
        
        # 실행 제한 시간 설정
        timeout = timeout or self.execution_timeout
        
        # 도구 이미지 이름 생성
        image_name = self._get_tool_image_name(tool_name, tool_version)
        
        # 취소 토큰 생성
        cancellation_token = asyncio.Event()
        self.cancellation_tokens[run_id] = cancellation_token
        
        # 실행 정보 저장
        self.running_tasks[run_id] = {
            "tool_name": tool_name,
            "tool_version": tool_version,
            "parameters": parameters,
            "context_id": context_id,
            "status": "queued",
            "start_time": None,
            "end_time": None,
            "container_id": None,
            "logs": [],
            "progress": 0.0,
            "result": None,
            "error": None
        }
        
        try:
            # 상태 업데이트
            self._update_status(run_id, "queued", callback=callback)
            
            # 도구 실행
            result = await self._run_tool_container(
                run_id=run_id,
                image_name=image_name,
                parameters=parameters,
                context_id=context_id,
                timeout=timeout,
                cancellation_token=cancellation_token,
                callback=callback
            )
            
            # 성공 시 결과 반환
            return result
        
        except asyncio.CancelledError:
            # 작업이 취소된 경우
            logger.info(f"실행 {run_id} 취소됨")
            self._update_status(run_id, "cancelled", callback=callback)
            
            # 컨테이너 정리
            await self._cleanup_container(run_id)
            
            return {
                "run_id": run_id,
                "status": "cancelled",
                "message": "실행이 취소되었습니다."
            }
        
        except Exception as e:
            # 오류 발생 시 상태 업데이트
            logger.error(f"실행 {run_id} 중 오류 발생: {str(e)}", exc_info=True)
            self._update_status(
                run_id,
                "failed",
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)},
                callback=callback
            )
            
            # 컨테이너 정리
            await self._cleanup_container(run_id)
            
            # 오류 전파
            raise ToolExecutionError(f"도구 실행 중 오류 발생: {str(e)}")
        
        finally:
            # 취소 토큰 제거
            if run_id in self.cancellation_tokens:
                del self.cancellation_tokens[run_id]
    
    async def cancel_execution(self, run_id: str) -> bool:
        """
        실행 취소
        
        Args:
            run_id: 실행 ID
            
        Returns:
            bool: 취소 성공 여부
        """
        # 실행 중인 작업 확인
        if run_id not in self.running_tasks:
            logger.warning(f"실행 {run_id}를 찾을 수 없음")
            return False
        
        # 이미 종료된 작업인 경우
        status = self.running_tasks[run_id]["status"]
        if status in ["completed", "failed", "cancelled"]:
            logger.warning(f"실행 {run_id}는 이미 {status} 상태임")
            return False
        
        # 취소 토큰 설정
        if run_id in self.cancellation_tokens:
            logger.info(f"실행 {run_id} 취소 중...")
            self.cancellation_tokens[run_id].set()
            
            # 컨테이너 정리
            await self._cleanup_container(run_id)
            
            # 상태 업데이트
            self.running_tasks[run_id]["status"] = "cancelled"
            self.running_tasks[run_id]["end_time"] = datetime.now().isoformat()
            
            return True
        
        return False
    
    def get_execution_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        실행 상태 조회
        
        Args:
            run_id: 실행 ID
            
        Returns:
            Optional[Dict[str, Any]]: 실행 상태 또는 None
        """
        if run_id not in self.running_tasks:
            return None
        
        task = self.running_tasks[run_id]
        
        # 응답 데이터 생성
        response = {
            "run_id": run_id,
            "tool_name": task["tool_name"],
            "tool_version": task["tool_version"],
            "status": task["status"],
            "progress": task["progress"],
            "logs": task["logs"][-10:] if task["logs"] else []  # 최근 로그 10개만 반환
        }
        
        # 시작/종료 시간 추가
        if task["start_time"]:
            response["started_at"] = task["start_time"]
        
        if task["end_time"]:
            response["completed_at"] = task["end_time"]
        
        # 결과 또는 오류 추가
        if task["status"] == "completed" and task["result"]:
            response["result"] = task["result"]
        
        if task["status"] == "failed" and task["error"]:
            response["error"] = task["error"]
        
        # 컨텍스트 ID 추가
        if task["context_id"]:
            response["context_id"] = task["context_id"]
        
        return response
    
    async def _run_tool_container(
        self,
        run_id: str,
        image_name: str,
        parameters: Dict[str, Any],
        context_id: Optional[str],
        timeout: int,
        cancellation_token: asyncio.Event,
        callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        도구 컨테이너 실행
        
        Args:
            run_id: 실행 ID
            image_name: 도구 이미지 이름
            parameters: 도구 매개변수
            context_id: 컨텍스트 ID
            timeout: 실행 제한 시간(초)
            cancellation_token: 취소 토큰
            callback: 상태 업데이트 콜백 함수
            
        Returns:
            Dict[str, Any]: 실행 결과
            
        Raises:
            ToolExecutionError: 도구 실행 중 오류 발생
        """
        # 시작 시간 기록
        start_time = datetime.now()
        self.running_tasks[run_id]["start_time"] = start_time.isoformat()
        
        # 상태 업데이트
        self._update_status(run_id, "running", callback=callback)
        
        # 매개변수 JSON 직렬화
        parameters_json = json.dumps(parameters)
        
        # 환경 변수 설정
        environment = {
            "RUN_ID": run_id,
            "PARAMETERS": parameters_json
        }
        
        if context_id:
            environment["CONTEXT_ID"] = context_id
        
        # 컨테이너 이름 설정
        container_name = f"mcp-tool-{run_id}"
        
        try:
            # 이미지 확인 및 풀
            try:
                self.docker_client.images.get(image_name)
                logger.info(f"이미지 {image_name} 이미 존재함")
            except ImageNotFound:
                logger.info(f"이미지 {image_name} 풀링 중...")
                self.docker_client.images.pull(image_name)
            
            # 컨테이너 실행
            logger.info(f"컨테이너 {container_name} 실행 중...")
            container = self.docker_client.containers.run(
                image=image_name,
                name=container_name,
                environment=environment,
                network=self.container_network,
                detach=True,
                auto_remove=False,  # 로그 수집을 위해 자동 제거 비활성화
                stdout=True,
                stderr=True
            )
            
            # 컨테이너 ID 저장
            self.running_tasks[run_id]["container_id"] = container.id
            
            # 로그 스트리밍 및 결과 대기
            result = await self._stream_logs_and_wait(
                run_id=run_id,
                container=container,
                timeout=timeout,
                cancellation_token=cancellation_token,
                callback=callback
            )
            
            # 종료 시간 기록
            end_time = datetime.now()
            self.running_tasks[run_id]["end_time"] = end_time.isoformat()
            
            # 상태 업데이트
            self._update_status(run_id, "completed", result=result, callback=callback)
            
            # 컨테이너 정리
            await self._cleanup_container(run_id)
            
            return {
                "run_id": run_id,
                "status": "completed",
                "result": result,
                "execution_time": (end_time - start_time).total_seconds()
            }
        
        except asyncio.TimeoutError:
            # 타임아웃 발생 시
            logger.error(f"실행 {run_id} 타임아웃 발생 ({timeout}초)")
            self._update_status(
                run_id,
                "failed",
                error={"code": "EXECUTION_TIMEOUT", "message": f"실행 시간 초과 ({timeout}초)"},
                callback=callback
            )
            
            # 컨테이너 정리
            await self._cleanup_container(run_id)
            
            raise ToolExecutionError(f"실행 시간 초과 ({timeout}초)")
        
        except DockerException as e:
            # Docker 오류 발생 시
            logger.error(f"Docker 오류 발생: {str(e)}")
            self._update_status(
                run_id,
                "failed",
                error={"code": "DOCKER_ERROR", "message": str(e)},
                callback=callback
            )
            
            raise ToolExecutionError(f"Docker 오류: {str(e)}")
    
    async def _stream_logs_and_wait(
        self,
        run_id: str,
        container: docker.models.containers.Container,
        timeout: int,
        cancellation_token: asyncio.Event,
        callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        컨테이너 로그 스트리밍 및 결과 대기
        
        Args:
            run_id: 실행 ID
            container: Docker 컨테이너
            timeout: 실행 제한 시간(초)
            cancellation_token: 취소 토큰
            callback: 상태 업데이트 콜백 함수
            
        Returns:
            Dict[str, Any]: 실행 결과
            
        Raises:
            asyncio.TimeoutError: 실행 시간 초과
            ToolExecutionError: 도구 실행 중 오류 발생
        """
        # 결과 파일 경로
        result_file = "/tmp/result.json"
        
        # 로그 스트리밍 작업
        log_task = asyncio.create_task(
            self._stream_container_logs(run_id, container, callback)
        )
        
        try:
            # 실행 완료 또는 타임아웃까지 대기
            start_time = time.time()
            
            while True:
                # 취소 확인
                if cancellation_token.is_set():
                    logger.info(f"실행 {run_id} 취소됨")
                    container.stop(timeout=2)
                    raise asyncio.CancelledError("실행이 취소되었습니다.")
                
                # 컨테이너 상태 확인
                container.reload()
                if container.status == "exited":
                    # 종료 코드 확인
                    exit_code = container.attrs["State"]["ExitCode"]
                    if exit_code != 0:
                        # 비정상 종료
                        error_message = f"컨테이너가 비정상 종료됨 (종료 코드: {exit_code})"
                        logger.error(error_message)
                        raise ToolExecutionError(error_message)
                    
                    # 결과 파일 확인
                    try:
                        result_data, _ = container.get_archive(result_file)
                        # 결과 파일 파싱 (실제로는 tarfile에서 추출해야 함)
                        # 여기서는 간단히 컨테이너 로그에서 결과를 파싱하는 것으로 대체
                        result = self._parse_result_from_logs(run_id)
                        return result
                    except APIError:
                        # 결과 파일이 없는 경우
                        logger.warning(f"결과 파일을 찾을 수 없음: {result_file}")
                        return {"message": "도구 실행 완료 (결과 없음)"}
                
                # 타임아웃 확인
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.error(f"실행 {run_id} 타임아웃 발생 ({timeout}초)")
                    container.stop(timeout=2)
                    raise asyncio.TimeoutError()
                
                # 잠시 대기
                await asyncio.sleep(1)
        
        finally:
            # 로그 스트리밍 작업 취소
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass
    
    async def _stream_container_logs(
        self,
        run_id: str,
        container: docker.models.containers.Container,
        callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> None:
        """
        컨테이너 로그 스트리밍
        
        Args:
            run_id: 실행 ID
            container: Docker 컨테이너
            callback: 상태 업데이트 콜백 함수
        """
        try:
            # 로그 스트림 설정
            log_stream = container.logs(stream=True, follow=True)
            
            # 로그 처리
            for log_line in log_stream:
                if isinstance(log_line, bytes):
                    log_line = log_line.decode("utf-8").strip()
                
                # 로그가 비어있는 경우 무시
                if not log_line:
                    continue
                
                # 로그 저장
                timestamp = datetime.now().isoformat()
                log_entry = {
                    "timestamp": timestamp,
                    "level": "info",
                    "message": log_line
                }
                
                # 진행률 파싱
                progress = self._parse_progress_from_log(log_line)
                if progress is not None:
                    log_entry["progress"] = progress
                    self.running_tasks[run_id]["progress"] = progress
                
                # 로그 추가
                self.running_tasks[run_id]["logs"].append(log_entry)
                
                # 콜백 호출
                if callback:
                    status_data = {
                        "run_id": run_id,
                        "status": "running",
                        "progress": self.running_tasks[run_id]["progress"],
                        "log": log_entry
                    }
                    callback(run_id, status_data)
                
                # 로그 출력
                logger.debug(f"[{run_id}] {log_line}")
                
                # 취소 확인을 위한 짧은 대기
                await asyncio.sleep(0.01)
        
        except Exception as e:
            logger.error(f"로그 스트리밍 중 오류 발생: {str(e)}", exc_info=True)
    
    def _parse_progress_from_log(self, log_line: str) -> Optional[float]:
        """
        로그에서 진행률 파싱
        
        Args:
            log_line: 로그 라인
            
        Returns:
            Optional[float]: 진행률 또는 None
        """
        try:
            # 진행률 표시 형식: PROGRESS: 50.0
            if log_line.startswith("PROGRESS:"):
                progress_str = log_line.split("PROGRESS:")[1].strip()
                progress = float(progress_str)
                return min(100.0, max(0.0, progress))
        except (IndexError, ValueError):
            pass
        
        return None
    
    def _parse_result_from_logs(self, run_id: str) -> Dict[str, Any]:
        """
        로그에서 결과 파싱
        
        Args:
            run_id: 실행 ID
            
        Returns:
            Dict[str, Any]: 실행 결과
        """
        # 결과 표시 형식: RESULT: {"key": "value"}
        for log_entry in reversed(self.running_tasks[run_id]["logs"]):
            log_line = log_entry["message"]
            if log_line.startswith("RESULT:"):
                try:
                    result_json = log_line.split("RESULT:")[1].strip()
                    return json.loads(result_json)
                except (IndexError, json.JSONDecodeError) as e:
                    logger.error(f"결과 파싱 중 오류 발생: {str(e)}")
                    break
        
        # 기본 결과
        return {"message": "도구 실행 완료 (결과 없음)"}
    
    async def _cleanup_container(self, run_id: str) -> None:
        """
        컨테이너 정리
        
        Args:
            run_id: 실행 ID
        """
        # 컨테이너 ID 확인
        container_id = self.running_tasks.get(run_id, {}).get("container_id")
        if not container_id:
            return
        
        try:
            # 컨테이너 조회
            container = self.docker_client.containers.get(container_id)
            
            # 컨테이너 상태 확인
            container.reload()
            
            # 실행 중인 경우 중지
            if container.status == "running":
                logger.info(f"컨테이너 {container_id} 중지 중...")
                container.stop(timeout=2)
            
            # 컨테이너 제거
            logger.info(f"컨테이너 {container_id} 제거 중...")
            container.remove(force=True)
            
            # 컨테이너 ID 제거
            self.running_tasks[run_id]["container_id"] = None
        
        except DockerException as e:
            logger.error(f"컨테이너 정리 중 오류 발생: {str(e)}")
        
        except Exception as e:
            logger.error(f"컨테이너 정리 중 예기치 않은 오류 발생: {str(e)}", exc_info=True)
    
    def _get_tool_image_name(self, tool_name: str, tool_version: Optional[str]) -> str:
        """
        도구 이미지 이름 생성
        
        Args:
            tool_name: 도구 이름
            tool_version: 도구 버전
            
        Returns:
            str: 도구 이미지 이름
        """
        # 도구 이름 정규화
        normalized_name = tool_name.lower().replace("_", "-")
        
        # 버전 지정 여부에 따라 이미지 이름 생성
        if tool_version:
            return f"mcp/tool-{normalized_name}:{tool_version}"
        else:
            return f"mcp/tool-{normalized_name}:latest"
    
    def _update_status(
        self,
        run_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> None:
        """
        실행 상태 업데이트
        
        Args:
            run_id: 실행 ID
            status: 상태
            result: 결과
            error: 오류
            callback: 상태 업데이트 콜백 함수
        """
        if run_id not in self.running_tasks:
            return
        
        # 상태 업데이트
        self.running_tasks[run_id]["status"] = status
        
        # 결과 또는 오류 업데이트
        if result is not None:
            self.running_tasks[run_id]["result"] = result
        
        if error is not None:
            self.running_tasks[run_id]["error"] = error
        
        # 종료 상태인 경우 종료 시간 기록
        if status in ["completed", "failed", "cancelled"] and not self.running_tasks[run_id]["end_time"]:
            self.running_tasks[run_id]["end_time"] = datetime.now().isoformat()
        
        # 콜백 호출
        if callback:
            status_data = self.get_execution_status(run_id)
            if status_data:
                callback(run_id, status_data)


# ----- 사용 예시 -----

async def example_usage():
    """사용 예시"""
    # 도구 실행 관리자 생성
    executor = ToolExecutor()
    
    # 상태 업데이트 콜백 함수
    def status_callback(run_id: str, status: Dict[str, Any]) -> None:
        print(f"상태 업데이트: {status}")
    
    try:
        # 도구 실행
        result = await executor.execute_tool(
            tool_name="echo",
            tool_version="latest",
            parameters={"message": "Hello, World!"},
            callback=status_callback
        )
        
        print(f"실행 결과: {result}")
    
    except Exception as e:
        print(f"오류 발생: {str(e)}")


if __name__ == "__main__":
    asyncio.run(example_usage()) 