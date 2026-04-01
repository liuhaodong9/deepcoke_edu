from fastapi import FastAPI, Depends  # 导入 FastAPI 和 Depends 依赖
from sqlalchemy import create_engine, Column, Integer, String, Text, TIMESTAMP, ForeignKey  # 导入 SQLAlchemy 组件
from sqlalchemy.ext.declarative import declarative_base  # 定义数据库模型
from sqlalchemy.orm import sessionmaker, Session, relationship  # 处理数据库会话
from uuid import uuid4  # 生成唯一 session_id（Python 内置库，无需安装）
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.sql import func  # 导入 SQL 函数
from datetime import datetime  # 导入 datetime
from openai import OpenAI  # DeepSeek 兼容 OpenAI API
from starlette.responses import StreamingResponse
import asyncio
import traceback
import logging
from pydantic import BaseModel
import hashlib

# ── DeepCoke Pipeline ──────────────────────────────────────────────
from deepcoke.pipeline import process_question

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deepcoke")

app = FastAPI() # 创建一个 FastAPI「实例」

# 使用 config 中的 LLM 配置（默认 Ollama 本地 Qwen3）
from deepcoke import config as _cfg
DEEPSEEK_API_KEY = _cfg.DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL = _cfg.DEEPSEEK_BASE_URL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# 允许前端访问后端（CORS 处理）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有前端访问
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = "mysql+pymysql://root:123456@127.0.0.1:3306/chat_db?charset=utf8mb4"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)  # 创建数据库会话
Base = declarative_base()  # 创建数据库模型基类

# 定义用户表（存储注册用户）
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    nickname = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

# 定义会话表（存储用户 ID 和会话 ID）
class ChatSession(Base):
    __tablename__ = "chat_sessions"  # 表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    user_id = Column(String(50), nullable=False)  # 用户 ID（标识用户）
    session_id = Column(String(50), unique=True, nullable=False)  # 唯一会话 ID（用于存储对话）

# 定义消息表（存储聊天记录）
class Message(Base):
    __tablename__ = "messages"  # 表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    session_id = Column(String(50), ForeignKey("chat_sessions.session_id"), nullable=False)  # 关联会话 ID
    user_message = Column(Text, nullable=False)  # 用户输入的消息
    bot_response = Column(Text, nullable=False)  # AI 生成的回复
    timestamp = Column(TIMESTAMP, nullable=False)  # 记录时间戳

# 延迟初始化数据库（在 FastAPI 启动事件中执行，避免模块加载时 MySQL 未启动导致崩溃）
@app.on_event("startup")
def _startup_init_db():
    try:
        Base.metadata.create_all(bind=engine)
        # 创建默认管理员账号
        db = SessionLocal()
        try:
            if not db.query(User).filter(User.username == "admin").first():
                admin = User(
                    username="admin",
                    password_hash=hashlib.sha256("123456".encode('utf-8')).hexdigest(),
                    nickname="管理员"
                )
                db.add(admin)
                db.commit()
                print("已创建默认管理员账号: admin / 123456")
        finally:
            db.close()
        logger.info("MySQL 数据库初始化成功")
    except Exception as e:
        logger.warning(f"MySQL 数据库初始化失败（聊天记录功能不可用）: {e}")
        logger.warning("请确保 MySQL 服务已启动并且 chat_db 数据库已创建")

# 依赖项：获取数据库会话
def get_db():
    db = SessionLocal()  # 获取数据库会话
    try:
        yield db  # 提供数据库连接
    finally:
        db.close()  # 关闭数据库连接

def hash_password(password: str) -> str:
    """对密码进行 SHA-256 哈希"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

class LoginForm(BaseModel):
    username: str
    password: str

class RegisterForm(BaseModel):
    username: str
    password: str
    nickname: str = ""

@app.post("/login")
def login(form: LoginForm, db: Session = Depends(get_db)):
    """
    数据库验证登录：
    - 成功返回: {"status":"ok","token":"...","username":"...","nickname":"..."}
    - 失败返回: "fail"
    """
    user = db.query(User).filter(User.username == form.username).first()
    if user and user.password_hash == hash_password(form.password):
        return {
            "status": "ok",
            "token": "I have login",
            "username": user.username,
            "nickname": user.nickname or user.username
        }
    return "fail"

@app.post("/register")
def register(form: RegisterForm, db: Session = Depends(get_db)):
    """
    用户注册：
    - 成功返回: {"status":"ok","message":"注册成功"}
    - 用户名已存在: {"status":"fail","message":"用户名已存在"}
    """
    existing = db.query(User).filter(User.username == form.username).first()
    if existing:
        return {"status": "fail", "message": "用户名已存在"}

    new_user = User(
        username=form.username,
        password_hash=hash_password(form.password),
        nickname=form.nickname if form.nickname else form.username
    )
    db.add(new_user)
    db.commit()
    return {"status": "ok", "message": "注册成功"}

# 1️⃣ **创建新会话**
@app.post("/new_session/")
async def create_session(user_id: str, db: Session = Depends(get_db)):
    """
    - 生成一个新的 session_id
    - 存储到 chat_sessions 表
    - 返回给用户 session_id
    """
    session_id = str(uuid4())  # 生成唯一 session_id
    new_session = ChatSession(user_id=user_id, session_id=session_id)  # 创建会话对象
    db.add(new_session)  # 添加到数据库
    db.commit()  # 提交事务

    # ✅ 直接存储 bot 欢迎消息
    welcome_message = Message(
        session_id=session_id,
        user_message="",  # 空用户消息
        bot_response="您好！我是焦化大语言智能问答与分析系统DeepCoke，有什么可以帮助你的？",  # ✅ 直接存入 bot 消息
        timestamp=datetime.utcnow()
    )
    db.add(welcome_message)
    db.commit()

    return {"session_id": session_id}  # 返回 session_id

# ✅ **DeepCoke 知识增强问答端点（RAG + ESCARGOT推理 + 知识图谱）**
@app.post("/chat/")
async def chat(session_id: str, user_message: str, db: Session = Depends(get_db)):
    async def generate():
        bot_response_parts = []

        try:
            # 使用 DeepCoke 知识增强管线处理问题
            # 管线内部完成：问题分类 → 中英翻译 → 向量检索 + KG检索 →
            # ESCARGOT推理(复杂问题) → 证据驱动回答生成 → 延伸问题生成
            async for piece in process_question(user_message):
                bot_response_parts.append(piece)
                yield piece
                await asyncio.sleep(0)

        except Exception as e:
            logger.error(f"Pipeline error: {repr(e)}")
            traceback.print_exc()
            # 管线失败时回退到简单 DeepSeek 调用
            try:
                fallback_stream = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "你是焦化大语言智能问答与分析系统DeepCoke，由苏州龙泰氢一能源科技有限公司研发。"},
                        {"role": "user", "content": user_message},
                    ],
                    stream=True,
                )
                for chunk in fallback_stream:
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "content", None)
                    if not piece:
                        continue
                    bot_response_parts.append(piece)
                    yield piece
                    await asyncio.sleep(0)
            except Exception as e2:
                logger.error(f"Fallback error: {repr(e2)}")
        finally:
            # 流结束或异常都尽量把已有内容落库
            full_reply = "".join(bot_response_parts).strip()
            try:
                new_message = Message(
                    session_id=session_id,
                    user_message=user_message,
                    bot_response=full_reply if full_reply else "（空响应或被中断）",
                    timestamp=datetime.utcnow()
                )
                db.add(new_message)
                db.commit()
            except Exception as e2:
                db.rollback()
                logger.error(f"db commit error: {repr(e2)}")

    # 保持与前端相同的流式响应格式
    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 避免某些反向代理缓冲
        }
    )

# 3️⃣ **查询用户的所有会话**
@app.get("/user_sessions/")
async def get_user_sessions(user_id: str, db: Session = Depends(get_db)):
    """
    - 查询某个用户的所有会话
    - 返回按照最后的消息时间排序（最新的在上面）
    - 使用该会话的第一条用户输入作为名称
    """
    sessions = db.query(ChatSession).filter(ChatSession.user_id == user_id).all()

    session_list = []
    for session in sessions:
        # 获取该会话的第一条用户消息
        first_message = db.query(Message).filter(
            Message.session_id == session.session_id,
            Message.user_message != ""
        ).order_by(Message.timestamp).first()

        # 默认标题（如果没有用户输入，则显示 session_id 前 6 位）
        session_title = first_message.user_message[:10] if first_message else f"新对话"

        # 获取该会话最后的消息时间（用于排序）
        last_message_time = db.query(func.max(Message.timestamp)).filter(Message.session_id == session.session_id).scalar()

        session_list.append({
            "session_id": session.session_id,
            "title": session_title,
            "last_message_time": last_message_time or datetime.utcnow()
        })

    # **按最后消息时间排序（最近的会话在上面）**
    session_list = sorted(session_list, key=lambda x: x["last_message_time"], reverse=True)

    return session_list


# 4️⃣ **查询某个会话的所有聊天记录**
@app.get("/messages/")
async def get_messages(session_id: str, db: Session = Depends(get_db)):
    """
    - 查询某个 session_id 下的所有聊天记录
    - 交替返回 user 和 bot 的消息
    """
    messages = db.query(Message).filter(Message.session_id == session_id).order_by(Message.timestamp.asc()).all()

    chat_history = []
    for msg in messages:
        if msg.user_message.strip():  # 过滤掉空的 user_message
            chat_history.append({"text": msg.user_message, "type": "user"})
        if msg.bot_response.strip():  # 过滤掉空的 bot_response
            chat_history.append({"text": msg.bot_response, "type": "bot"})

    return chat_history  # ✅ user 和 bot 按顺序交替返回