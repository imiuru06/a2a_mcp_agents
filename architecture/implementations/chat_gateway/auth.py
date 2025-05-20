#!/usr/bin/env python3
"""
Chat Gateway - 인증 및 토큰 검증 모듈

이 모듈은 사용자 인증 및 JWT 토큰 검증을 처리합니다.
"""

import os
import time
import json
import logging
import uuid
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("auth")

# JWT 설정 (실제로는 환경 변수나 설정 파일에서 가져와야 함)
JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_MINUTES = int(os.environ.get("JWT_EXPIRATION_MINUTES", "60"))

# 세션 저장소 (실제로는 Redis 등을 사용해야 함)
session_store: Dict[str, Dict[str, Any]] = {}

# 보안 스키마
security = HTTPBearer()


class TokenData:
    """토큰 데이터 클래스"""
    
    def __init__(self, username: str, user_id: str, roles: List[str], exp: int):
        self.username = username
        self.user_id = user_id
        self.roles = roles
        self.exp = exp
    
    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "TokenData":
        """JWT 페이로드에서 TokenData 생성"""
        return cls(
            username=payload.get("sub"),
            user_id=payload.get("user_id"),
            roles=payload.get("roles", []),
            exp=payload.get("exp")
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "username": self.username,
            "user_id": self.user_id,
            "roles": self.roles,
            "exp": self.exp
        }


def create_jwt_token(
    username: str,
    user_id: str,
    roles: List[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    JWT 토큰 생성
    
    Args:
        username: 사용자 이름
        user_id: 사용자 ID
        roles: 사용자 역할 목록
        expires_delta: 만료 시간 델타
        
    Returns:
        str: JWT 토큰
    """
    roles = roles or ["user"]
    expires_delta = expires_delta or timedelta(minutes=JWT_EXPIRATION_MINUTES)
    
    expire = datetime.utcnow() + expires_delta
    
    payload = {
        "sub": username,
        "user_id": user_id,
        "roles": roles,
        "exp": expire.timestamp(),
        "iat": datetime.utcnow().timestamp(),
        "jti": str(uuid.uuid4())
    }
    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> Dict[str, Any]:
    """
    JWT 토큰 디코딩
    
    Args:
        token: JWT 토큰
        
    Returns:
        Dict[str, Any]: 토큰 페이로드
        
    Raises:
        HTTPException: 토큰이 유효하지 않은 경우
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "TOKEN_EXPIRED",
                "message": "토큰이 만료되었습니다."
            }
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_TOKEN",
                "message": "유효하지 않은 토큰입니다."
            }
        )


def create_session(user_id: str, token: str, user_data: Dict[str, Any] = None) -> str:
    """
    세션 생성
    
    Args:
        user_id: 사용자 ID
        token: JWT 토큰
        user_data: 추가 사용자 데이터
        
    Returns:
        str: 세션 ID
    """
    session_id = str(uuid.uuid4())
    user_data = user_data or {}
    
    session_store[session_id] = {
        "user_id": user_id,
        "token": token,
        "user_data": user_data,
        "created_at": datetime.now().isoformat(),
        "last_activity": datetime.now().isoformat()
    }
    
    return session_id


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    세션 조회
    
    Args:
        session_id: 세션 ID
        
    Returns:
        Optional[Dict[str, Any]]: 세션 데이터 또는 None
    """
    return session_store.get(session_id)


def update_session_activity(session_id: str) -> bool:
    """
    세션 활동 시간 업데이트
    
    Args:
        session_id: 세션 ID
        
    Returns:
        bool: 업데이트 성공 여부
    """
    if session_id in session_store:
        session_store[session_id]["last_activity"] = datetime.now().isoformat()
        return True
    return False


def delete_session(session_id: str) -> bool:
    """
    세션 삭제
    
    Args:
        session_id: 세션 ID
        
    Returns:
        bool: 삭제 성공 여부
    """
    if session_id in session_store:
        del session_store[session_id]
        return True
    return False


# ----- 의존성 함수 -----

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> TokenData:
    """
    현재 사용자 조회 (JWT 토큰 검증)
    
    Args:
        credentials: HTTP 인증 정보
        
    Returns:
        TokenData: 토큰 데이터
        
    Raises:
        HTTPException: 인증 실패 시
    """
    try:
        token = credentials.credentials
        payload = decode_jwt_token(token)
        token_data = TokenData.from_payload(payload)
        
        # 토큰 만료 확인
        if token_data.exp < time.time():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error_code": "TOKEN_EXPIRED",
                    "message": "토큰이 만료되었습니다."
                }
            )
        
        return token_data
    
    except Exception as e:
        logger.error(f"인증 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "AUTHENTICATION_FAILED",
                "message": "인증에 실패했습니다."
            }
        )


async def get_session_user(request: Request) -> Dict[str, Any]:
    """
    세션에서 사용자 조회
    
    Args:
        request: HTTP 요청
        
    Returns:
        Dict[str, Any]: 세션 데이터
        
    Raises:
        HTTPException: 세션이 유효하지 않은 경우
    """
    session_id = request.headers.get("X-Session-ID")
    
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "SESSION_REQUIRED",
                "message": "세션 ID가 필요합니다."
            }
        )
    
    session = get_session(session_id)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_SESSION",
                "message": "유효하지 않은 세션입니다."
            }
        )
    
    # 세션 활동 시간 업데이트
    update_session_activity(session_id)
    
    return session


async def require_role(
    required_roles: List[str],
    token_data: TokenData = Depends(get_current_user)
) -> TokenData:
    """
    사용자 역할 확인
    
    Args:
        required_roles: 필요한 역할 목록
        token_data: 토큰 데이터
        
    Returns:
        TokenData: 토큰 데이터
        
    Raises:
        HTTPException: 권한이 없는 경우
    """
    # 역할 확인
    if not any(role in token_data.roles for role in required_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "INSUFFICIENT_PERMISSIONS",
                "message": "이 작업을 수행할 권한이 없습니다."
            }
        )
    
    return token_data


# ----- 인증 함수 -----

def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    사용자 인증
    
    실제로는 데이터베이스에서 사용자 조회 및 비밀번호 검증을 수행해야 함
    여기서는 간단한 예시만 구현
    
    Args:
        username: 사용자 이름
        password: 비밀번호
        
    Returns:
        Optional[Dict[str, Any]]: 인증된 사용자 정보 또는 None
    """
    # 테스트용 사용자 (실제로는 DB에서 조회)
    test_users = {
        "user123": {
            "user_id": "usr-123456",
            "username": "user123",
            "password": "p@ssw0rd",  # 실제로는 해시된 비밀번호를 저장해야 함
            "display_name": "홍길동",
            "roles": ["user"]
        },
        "admin": {
            "user_id": "usr-admin",
            "username": "admin",
            "password": "admin123",
            "display_name": "관리자",
            "roles": ["user", "admin"]
        }
    }
    
    # 사용자 조회
    user = test_users.get(username)
    
    # 사용자가 없거나 비밀번호가 일치하지 않는 경우
    if not user or user["password"] != password:
        return None
    
    # 비밀번호 필드 제거
    user_data = {k: v for k, v in user.items() if k != "password"}
    
    return user_data


# ----- 사용 예시 -----

def example_usage():
    """사용 예시"""
    # 사용자 인증
    user = authenticate_user("user123", "p@ssw0rd")
    
    if user:
        # JWT 토큰 생성
        token = create_jwt_token(
            username=user["username"],
            user_id=user["user_id"],
            roles=user["roles"]
        )
        
        # 세션 생성
        session_id = create_session(user["user_id"], token, user)
        
        print(f"토큰: {token}")
        print(f"세션 ID: {session_id}")
        
        # 토큰 디코딩
        payload = decode_jwt_token(token)
        print(f"페이로드: {payload}")
        
        # 세션 조회
        session = get_session(session_id)
        print(f"세션: {session}")
        
        # 세션 삭제
        deleted = delete_session(session_id)
        print(f"세션 삭제: {deleted}")
    else:
        print("인증 실패")


if __name__ == "__main__":
    example_usage() 