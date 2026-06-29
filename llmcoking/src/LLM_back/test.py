from fastapi import FastAPI, Depends, HTTPException, Header  # 导入 FastAPI 和 Depends 依赖
from sqlalchemy import create_engine, Column, Integer, String, Text, TIMESTAMP, ForeignKey  # 导入 SQLAlchemy 组件
from sqlalchemy import text as _sql_text_top  # 用于启动时 ALTER TABLE 加列
from sqlalchemy.ext.declarative import declarative_base  # 定义数据库模型
from sqlalchemy.orm import sessionmaker, Session, relationship  # 处理数据库会话
from uuid import uuid4  # 生成唯一 session_id（Python 内置库，无需安装）
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.sql import func  # 导入 SQL 函数
from datetime import datetime  # 导入 datetime
from openai import OpenAI  # DeepSeek 兼容 OpenAI API
from starlette.responses import StreamingResponse
import asyncio
import os
import traceback
import logging
from pydantic import BaseModel
from typing import List, Optional
import hashlib

# ── Admin papers router (上传 PDF/文档管理) ─────────────────────────
from admin_papers import router as admin_papers_router

# ── DeepCoke Pipeline ──────────────────────────────────────────────
# USE_ENHANCED_PIPELINE=true → 走 PaperQA2/NotebookLM 风格的 agent 全文阅读
# 否则 → 走旧版 chunk-based RAG
_USE_ENHANCED = os.getenv("USE_ENHANCED_PIPELINE", "false").lower() in ("1", "true", "yes")
if _USE_ENHANCED:
    from deepcoke.enhanced_pipeline_graph import process_question  # Agent 全文阅读
    logging.getLogger("deepcoke").info("[boot] Using ENHANCED pipeline (agent full-text)")
else:
    from deepcoke.pipeline_graph import process_question  # 旧版 chunk RAG
    logging.getLogger("deepcoke").info("[boot] Using LEGACY pipeline (chunk RAG)")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deepcoke")

app = FastAPI() # 创建一个 FastAPI「实例」

# 使用 config 中的 LLM 配置（默认 Ollama 本地 Qwen3）
from deepcoke import config as _cfg
DEEPSEEK_API_KEY = _cfg.DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL = _cfg.DEEPSEEK_BASE_URL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# 允许前端访问后端（CORS 处理）
# allow_origins=['*'] 不能和 allow_credentials=True 共用，这里前端走相对路径不带 cookie，credentials 关掉即可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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

# 用户 token 表（鉴权）— 由 auth.make_user_token_model 构造
from auth import (
    make_user_token_model, make_auth_middleware,
    issue_token as _issue_token, revoke_user_tokens as _revoke_user_tokens,
)
UserToken = make_user_token_model(Base)

# 定义文件夹表（用户的会话分类）
class ChatFolder(Base):
    __tablename__ = "chat_folders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), nullable=False)
    name = Column(String(50), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

# 定义会话表（存储用户 ID 和会话 ID）
class ChatSession(Base):
    __tablename__ = "chat_sessions"  # 表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    user_id = Column(String(50), nullable=False)  # 用户 ID（标识用户）
    session_id = Column(String(50), unique=True, nullable=False)  # 唯一会话 ID（用于存储对话）
    folder_id = Column(Integer, ForeignKey("chat_folders.id"), nullable=True)  # 所属文件夹（NULL 表示根目录）
    title = Column(String(100), nullable=True)  # 自定义会话名（NULL 时取首条消息）

# 定义消息表（存储聊天记录）
class Message(Base):
    __tablename__ = "messages"  # 表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    session_id = Column(String(50), ForeignKey("chat_sessions.session_id"), nullable=False)  # 关联会话 ID
    user_message = Column(Text, nullable=False)  # 用户输入的消息
    bot_response = Column(Text, nullable=False)  # AI 生成的回复
    timestamp = Column(TIMESTAMP, nullable=False)  # 记录时间戳

# 延迟初始化数据库（在 FastAPI 启动事件中执行，避免模块加载时 MySQL 未启动导致崩溃）
def _migrate_add_columns(conn):
    """给老库 chat_sessions 补 folder_id / title 列；老库没有就跳过。MySQL 没有 IF NOT EXISTS，捕获异常即可。"""
    for stmt in (
        "ALTER TABLE chat_sessions ADD COLUMN folder_id INT NULL",
        "ALTER TABLE chat_sessions ADD COLUMN title VARCHAR(100) NULL",
    ):
        try:
            conn.execute(_sql_text_top(stmt))
        except Exception as _e:
            # 1060 Duplicate column = 已经迁过，忽略
            if "Duplicate column" not in str(_e) and "1060" not in str(_e):
                logger.warning(f"migrate skipped: {stmt} -> {_e}")

# 注册鉴权中间件：除 /login /register /docs /papers/*/pdf 外的接口都需要 Bearer token
# LEGACY_BYPASS_TOKEN（默认 true）允许老前端的固定字符串 token，公网上线时设环境变量 AUTH_LEGACY_BYPASS=false
app.middleware("http")(make_auth_middleware(SessionLocal, UserToken))

# 挂载 admin papers 子路由(上传 PDF / 列表 / 删除 / 重抽 summary)
app.include_router(admin_papers_router)


@app.on_event("startup")
def _startup_init_db():
    try:
        Base.metadata.create_all(bind=engine)
        # 老库补列
        with engine.begin() as conn:
            _migrate_add_columns(conn)
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
    - 成功返回: {"status":"ok","token":"<urlsafe_32>","username":"...","nickname":"..."}
      token 是真实签发的随机串，30 天有效（环境变量 AUTH_TOKEN_TTL_DAYS 可调）
    - 失败返回: "fail"
    """
    user = db.query(User).filter(User.username == form.username).first()
    if user and user.password_hash == hash_password(form.password):
        token = _issue_token(db, UserToken, user.username)
        return {
            "status": "ok",
            "token": token,
            "username": user.username,
            "nickname": user.nickname or user.username,
        }
    return "fail"


@app.post("/logout")
def logout(db: Session = Depends(get_db), authorization: str = Header(default="")):
    """注销：作废当前 token 对应用户的所有 token。"""
    token = authorization.split(" ", 1)[1].strip() if authorization.lower().startswith("bearer ") else ""
    if not token:
        return {"status": "ok", "revoked": 0}
    rec = db.query(UserToken).filter(UserToken.token == token).first()
    if not rec:
        return {"status": "ok", "revoked": 0}
    n = _revoke_user_tokens(db, UserToken, rec.user_id)
    return {"status": "ok", "revoked": n}

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
        bot_response="您好！我是高校智慧化工软件平台 DeepResearch，有什么可以帮助你的？",  # ✅ 直接存入 bot 消息
        timestamp=datetime.utcnow()
    )
    db.add(welcome_message)
    db.commit()

    return {"session_id": session_id}  # 返回 session_id

# ✅ **DeepCoke 知识增强问答端点（RAG + ESCARGOT推理 + 知识图谱）**
@app.post("/chat/")
async def chat(session_id: str, user_message: str, db: Session = Depends(get_db)):
    # 读取最近 3 轮历史(给 query 跨轮补全用),按时间正序排列
    history = []
    try:
        rows = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.timestamp.desc())
            .limit(3)
            .all()
        )
        # rows 是降序(最新在前),反转成升序(老的在前)
        for row in reversed(rows):
            history.append({
                "user_message": row.user_message or "",
                "bot_response": row.bot_response or "",
            })
    except Exception as _e:
        logger.warning(f"load history skipped: {_e}")

    async def generate():
        bot_response_parts = []

        try:
            # 使用 DeepCoke 知识增强管线处理问题
            # 管线内部完成：问题分类 → 中英翻译 → 向量检索 + KG检索 →
            # ESCARGOT推理(复杂问题) → 证据驱动回答生成 → 延伸问题生成
            async for piece in process_question(user_message, history=history):
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
                        {"role": "system", "content": "你是高校智慧化工软件平台 DeepResearch，由苏州龙泰氢一能源科技有限公司研发。"},
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
                # 兜底:如果 session_id 在 chat_sessions 不存在(curl 直测/前端漏建),
                # 先 INSERT IGNORE 一行占位 session,避免 messages 外键 IntegrityError
                from sqlalchemy import text as _sql_text
                db.execute(
                    _sql_text(
                        "INSERT IGNORE INTO chat_sessions (user_id, session_id) "
                        "VALUES (:uid, :sid)"
                    ),
                    {"uid": "_orphan_", "sid": session_id},
                )
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
                logger.warning(f"db commit skipped: {type(e2).__name__}: {e2}")

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
    - 自定义 title 优先，否则取首条用户消息前 10 字
    - 同时返回 folder_id 以便前端按文件夹分组
    """
    sessions = db.query(ChatSession).filter(ChatSession.user_id == user_id).all()

    session_list = []
    for session in sessions:
        # 获取该会话的第一条用户消息
        first_message = db.query(Message).filter(
            Message.session_id == session.session_id,
            Message.user_message != ""
        ).order_by(Message.timestamp).first()

        # 标题优先级：自定义 title > 首条消息 > 默认
        if session.title:
            session_title = session.title
        elif first_message:
            session_title = first_message.user_message[:10]
        else:
            session_title = "新对话"

        # 获取该会话最后的消息时间（用于排序）
        last_message_time = db.query(func.max(Message.timestamp)).filter(Message.session_id == session.session_id).scalar()

        session_list.append({
            "session_id": session.session_id,
            "title": session_title,
            "folder_id": session.folder_id,
            "last_message_time": last_message_time or datetime.utcnow()
        })

    # **按最后消息时间排序（最近的会话在上面）**
    session_list = sorted(session_list, key=lambda x: x["last_message_time"], reverse=True)

    return session_list


# ── 会话单条增删改 ────────────────────────────────────────────────
@app.delete("/delete_session/")
async def delete_session(session_id: str, db: Session = Depends(get_db)):
    """删除单个会话及其所有消息。"""
    db.query(Message).filter(Message.session_id == session_id).delete(synchronize_session=False)
    deleted = db.query(ChatSession).filter(ChatSession.session_id == session_id).delete(synchronize_session=False)
    db.commit()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="session 不存在")
    return {"status": "ok", "deleted": session_id}


@app.put("/rename_session/")
async def rename_session(session_id: str, new_title: str, db: Session = Depends(get_db)):
    """给会话设一个自定义 title。"""
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="session 不存在")
    session.title = (new_title or "").strip()[:100] or None
    db.commit()
    return {"status": "ok", "session_id": session_id, "title": session.title}


# ── 批量操作 ──────────────────────────────────────────────────────
class SessionIdsBody(BaseModel):
    session_ids: List[str]


class MoveSessionsBody(BaseModel):
    session_ids: List[str]
    folder_id: Optional[int] = None  # null = 移回根目录


@app.post("/sessions/batch_delete")
async def batch_delete_sessions(body: SessionIdsBody, db: Session = Depends(get_db)):
    """一次性删除多个会话（含消息）。"""
    if not body.session_ids:
        return {"status": "ok", "deleted": 0}
    db.query(Message).filter(Message.session_id.in_(body.session_ids)).delete(synchronize_session=False)
    deleted = db.query(ChatSession).filter(ChatSession.session_id.in_(body.session_ids)).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok", "deleted": deleted}


@app.post("/sessions/move")
async def move_sessions(body: MoveSessionsBody, db: Session = Depends(get_db)):
    """把多个会话移到某文件夹（folder_id=None 表示移出文件夹）。"""
    if not body.session_ids:
        return {"status": "ok", "moved": 0}
    if body.folder_id is not None:
        folder = db.query(ChatFolder).filter(ChatFolder.id == body.folder_id).first()
        if not folder:
            raise HTTPException(status_code=404, detail="folder 不存在")
    updated = db.query(ChatSession).filter(ChatSession.session_id.in_(body.session_ids)).update(
        {ChatSession.folder_id: body.folder_id}, synchronize_session=False
    )
    db.commit()
    return {"status": "ok", "moved": updated, "folder_id": body.folder_id}


# ── 文件夹 CRUD ───────────────────────────────────────────────────
class FolderCreateBody(BaseModel):
    user_id: str
    name: str


class FolderRenameBody(BaseModel):
    new_name: str


@app.get("/folders/")
async def list_folders(user_id: str, db: Session = Depends(get_db)):
    """列出用户所有文件夹（按创建时间升序）。"""
    rows = db.query(ChatFolder).filter(ChatFolder.user_id == user_id).order_by(ChatFolder.created_at.asc()).all()
    return [{"id": f.id, "name": f.name} for f in rows]


@app.post("/folders/")
async def create_folder(body: FolderCreateBody, db: Session = Depends(get_db)):
    """新建一个文件夹。"""
    name = (body.name or "").strip()[:50]
    if not name:
        raise HTTPException(status_code=400, detail="文件夹名不能为空")
    folder = ChatFolder(user_id=body.user_id, name=name)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return {"id": folder.id, "name": folder.name}


@app.put("/folders/{folder_id}")
async def rename_folder(folder_id: int, body: FolderRenameBody, db: Session = Depends(get_db)):
    """重命名文件夹。"""
    folder = db.query(ChatFolder).filter(ChatFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="folder 不存在")
    new_name = (body.new_name or "").strip()[:50]
    if not new_name:
        raise HTTPException(status_code=400, detail="文件夹名不能为空")
    folder.name = new_name
    db.commit()
    return {"id": folder.id, "name": folder.name}


@app.delete("/folders/{folder_id}")
async def delete_folder(folder_id: int, db: Session = Depends(get_db)):
    """删除文件夹本身，里面的会话回到根目录（不删除会话）。"""
    folder = db.query(ChatFolder).filter(ChatFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="folder 不存在")
    db.query(ChatSession).filter(ChatSession.folder_id == folder_id).update(
        {ChatSession.folder_id: None}, synchronize_session=False
    )
    db.delete(folder)
    db.commit()
    return {"status": "ok", "deleted_folder_id": folder_id}


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


# ── 人脸识别与主动问候（Mock 接口，后续对接摄像头 + InsightFace）──

# Mock 学生数据库
_student_db = {
    "stu_001": {"name": "张同学", "last_topic": "焦炭CRI/CSR指标", "visit_count": 3},
    "stu_002": {"name": "李同学", "last_topic": "捣固焦工艺", "visit_count": 1},
}


@app.post("/face/recognize")
async def face_recognize(image_b64: str = ""):
    """
    人脸识别接口（Mock）
    实际部署时：接收摄像头帧 → InsightFace 识别 → 返回学生信息
    """
    # Mock: 模拟识别到 stu_001
    mock_student_id = "stu_001"
    student = _student_db.get(mock_student_id)
    if student:
        return {
            "status": "recognized",
            "student_id": mock_student_id,
            "name": student["name"],
            "visit_count": student["visit_count"],
            "last_topic": student["last_topic"],
            "greeting": f"你好 {student['name']}！欢迎回来，上次我们聊了「{student['last_topic']}」，今天想继续学习还是换个话题？",
            "note": "当前为模拟模式，未连接摄像头"
        }
    return {
        "status": "new_face",
        "greeting": "你好！我是 DeepCoke 智能助教，欢迎第一次使用，请问你想了解什么？",
        "note": "当前为模拟模式，未连接摄像头"
    }


@app.post("/face/register")
async def face_register(name: str = "", student_id: str = ""):
    """
    人脸注册接口（Mock）
    实际部署时：采集人脸特征 → 存入数据库
    """
    new_id = student_id or f"stu_{len(_student_db) + 1:03d}"
    _student_db[new_id] = {"name": name or "新同学", "last_topic": "", "visit_count": 0}
    return {
        "status": "ok",
        "student_id": new_id,
        "message": f"已注册学生：{name or '新同学'}（模拟模式）"
    }


# 煤样数据分页查询
@app.get("/all_coals_page/")
async def all_coals_page(page: int = 1, page_size: int = 10):
    """分页查询所有煤样数据，供前端表格展示。"""
    from deepcoke.coal_agent.coal_db import get_all_coals
    rows = get_all_coals()
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    return {"total": total, "page": page, "page_size": page_size, "data": rows[start:end]}


# ─── 文献库 API ───────────────────────────────────────────────────
@app.get("/papers/{paper_id}/pdf")
async def get_paper_pdf(paper_id: int):
    """返回某篇文献的 PDF 文件,前端可 iframe/新窗口打开。"""
    import sqlite3
    import re
    from pathlib import Path
    from urllib.parse import quote
    from starlette.responses import FileResponse
    from fastapi import HTTPException
    from deepcoke import config as _c

    db = sqlite3.connect(str(_c.DATA_DIR / "papers.db"))
    row = db.execute("SELECT file_path, title FROM papers WHERE id = ?", (paper_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"paper_id={paper_id} 不存在")
    file_path = row[0] or ""   # 直接用库里的路径(Linux 正斜杠;Path 跨平台兼容,勿做 / → \ 替换)
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail=f"PDF 文件不存在: {file_path}")

    # 文件名: ASCII 版做 fallback,UTF-8 版用 RFC 5987 编码避免触发 uvicorn 的 header 校验
    raw = (row[1] or f"paper_{paper_id}")[:80]
    ascii_name = re.sub(r"[^A-Za-z0-9._\- ]", "_", raw).strip("_ ") or f"paper_{paper_id}"
    utf8_name = quote(raw + ".pdf", safe="")
    disposition = f"inline; filename=\"{ascii_name}.pdf\"; filename*=UTF-8''{utf8_name}"
    return FileResponse(
        file_path,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


@app.get("/papers/{paper_id}/figure")
async def get_paper_figure(paper_id: int, page: int = 0, bbox: str = ""):
    """渲染某篇 PDF 指定页的图(按图注 bbox 裁图注上方一条带),返回 PNG。
    给回答里的"关键图片"展示用,鉴权豁免(<img> 带不了 header,同 /pdf)。"""
    import sqlite3
    from pathlib import Path
    from starlette.responses import Response
    from fastapi import HTTPException
    from deepcoke import config as _c
    from deepcoke.ingestion.figure_render import render_figure_crop, render_page_png

    db = sqlite3.connect(str(_c.DATA_DIR / "papers.db"))
    row = db.execute("SELECT file_path FROM papers WHERE id = ?", (paper_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"paper_id={paper_id} 不存在")
    file_path = row[0] or ""   # 直接用库里的路径(Linux 正斜杠;Path 跨平台兼容,勿做 / → \ 替换)
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail=f"PDF 文件不存在: {file_path}")

    cb = None
    if bbox:
        try:
            parts = [float(x) for x in bbox.replace("[", "").replace("]", "").split(",") if x.strip()]
            cb = tuple(parts) if len(parts) == 4 else None
        except ValueError:
            cb = None
    png = render_figure_crop(file_path, int(page), cb) if cb else None
    if png is None:
        png = render_page_png(file_path, int(page))   # 无 bbox/裁图失败 → 退整页
    if png is None:
        raise HTTPException(status_code=500, detail="图渲染失败")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/papers/{paper_id}")
async def get_paper_meta(paper_id: int):
    """返回单篇文献的完整 metadata。"""
    import sqlite3
    from fastapi import HTTPException
    from deepcoke import config as _c

    db = sqlite3.connect(str(_c.DATA_DIR / "papers.db"))
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT id, title, authors, year, category, journal, abstract FROM papers WHERE id = ?",
        (paper_id,),
    ).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"paper_id={paper_id} 不存在")
    return dict(row)


@app.get("/chunk/{chunk_id}/full")
async def get_chunk_full(chunk_id: str):
    """调试端点:返回 chunk 的完整原文(不截断)+ 元数据,
    用于对比 LITQA_META.chunks[i].text(截断 1500 字)和 chunks 库里的真实内容。

    chunk_id 格式约定:f"{paper_id}_{chunk_index}",
    例:GET /chunk/5_1/full → 返回 paper_id=5 第 1 个 chunk 的全文。
    """
    from fastapi import HTTPException
    from deepcoke.vectorstore.chromadb_store import get_chroma_client
    from deepcoke import config as _c

    client = get_chroma_client()
    col = client.get_collection(_c.CHROMADB_COLLECTION)

    # 优先按 ChromaDB 内部 ID 直查
    try:
        res = col.get(ids=[chunk_id], include=["documents", "metadatas"])
    except Exception:
        res = None
    found = res and res.get("ids") and len(res["ids"]) > 0

    # 兜底:按 paper_id + chunk_index 双重过滤(应付 ID 格式不是 pid_cidx 的老数据)
    if not found:
        try:
            pid_str, cidx_str = chunk_id.split("_", 1)
            pid, cidx = int(pid_str), int(cidx_str)
            res = col.get(
                where={"$and": [{"paper_id": pid}, {"chunk_index": cidx}]},
                include=["documents", "metadatas"],
            )
            found = res and res.get("ids") and len(res["ids"]) > 0
        except (ValueError, KeyError):
            pass

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"chunk_id={chunk_id} 未在 ChromaDB 中找到(尝试了 ids 直查 + paper_id/chunk_index 兜底过滤)",
        )

    return {
        "chunk_id": res["ids"][0],
        "text": res["documents"][0],
        "metadata": res["metadatas"][0],
        "text_length": len(res["documents"][0]),
    }


# ─── 知识图谱子图(给前端 vis-network 渲染)──────────────────────
@app.get("/paper_graph")
async def paper_graph(paper_ids: str, scores: str = ""):
    """给定一组 paper_id,返回它们在知识图谱中的子图(vis-network 格式)。

    优先从 Neo4j 出真实子图(Paper + 一跳邻居 Concept/Method/Material/Property);
    Neo4j 未启动或图谱未灌入时,退化为 Query→Papers 放射图(只用 papers.db 元数据)。

    Query:
      paper_ids=1,2,3      逗号分隔的 paper_id 列表
      scores=0.81,0.78,... (可选)对应每个 paper_id 的检索相似度,作为边 label
    Response: { "nodes": [{id,label,group,title?}], "edges": [{from,to,label,arrows}], "source": ... }
    """
    pids = [int(x) for x in paper_ids.split(",") if x.strip().isdigit()]
    if not pids:
        return {"nodes": [], "edges": [], "source": "empty"}

    score_list = []
    if scores:
        for s in scores.split(","):
            try:
                score_list.append(float(s))
            except ValueError:
                score_list.append(None)
    while len(score_list) < len(pids):
        score_list.append(None)
    score_map = {pid: score_list[i] for i, pid in enumerate(pids)}

    # 1) 优先 Neo4j
    from deepcoke.knowledge_graph.neo4j_client import execute_cypher, get_driver
    if get_driver() is not None:
        cypher = """
        MATCH (p:Paper)
        WHERE p.paper_id IN $pids
        OPTIONAL MATCH (p)-[r]->(n)
        WHERE labels(n)[0] IN ['Concept','Method','Material','Property']
        RETURN p.paper_id AS pid, p.title AS ptitle, p.year AS pyear,
               type(r) AS rtype, labels(n)[0] AS ntype,
               coalesce(n.name, n.title, '') AS nname
        """
        rows = execute_cypher(cypher, {"pids": pids})
        if rows:
            return {**_build_graph_from_neo4j(rows, score_map), "source": "neo4j"}

    # 2) Fallback: Query→Papers 放射,只用 papers.db
    return {**_build_graph_fallback(pids, score_map), "source": "fallback"}


def _build_graph_from_neo4j(rows: list[dict], score_map: dict) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges: set[tuple] = set()
    for r in rows:
        pid = r["pid"]
        p_id = f"P{pid}"
        if p_id not in nodes:
            title = r.get("ptitle") or f"Paper {pid}"
            year = r.get("pyear")
            label = title[:40] + ("…" if len(title) > 40 else "")
            if year:
                label = f"{label}\n({year})"
            nodes[p_id] = {
                "id": p_id,
                "label": label,
                "group": "Paper",
                "title": title,
                "paper_id": pid,
                "score": score_map.get(pid),
            }
        rtype = r.get("rtype")
        ntype = r.get("ntype")
        nname = r.get("nname")
        if rtype and ntype and nname:
            n_id = f"{ntype[0]}_{nname}"
            if n_id not in nodes:
                nodes[n_id] = {
                    "id": n_id,
                    "label": nname[:24] + ("…" if len(nname) > 24 else ""),
                    "group": ntype,
                    "title": nname,
                }
            ekey = (p_id, n_id, rtype)
            if ekey not in seen_edges:
                edges.append({"from": p_id, "to": n_id, "label": rtype, "arrows": "to"})
                seen_edges.add(ekey)
    return {"nodes": list(nodes.values()), "edges": edges}


def _build_graph_fallback(pids: list[int], score_map: dict) -> dict:
    """Neo4j 不可用时:Query → Papers 放射图,边 label = 相似度。"""
    import sqlite3
    from deepcoke import config as _c

    db = sqlite3.connect(str(_c.DATA_DIR / "papers.db"))
    db.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(pids))
    rows = db.execute(
        f"SELECT id, title, year FROM papers WHERE id IN ({placeholders})",
        pids,
    ).fetchall()
    db.close()
    by_id = {r["id"]: r for r in rows}

    nodes = [{"id": "Q", "label": "本次查询", "group": "Query", "title": "用户问题"}]
    edges = []
    # 按 pids 原序输出,保留与 score 的对应
    for pid in pids:
        r = by_id.get(pid)
        if not r:
            continue
        title = r["title"] or f"Paper {pid}"
        year = r["year"]
        label = title[:40] + ("…" if len(title) > 40 else "")
        if year:
            label = f"{label}\n({year})"
        nodes.append({
            "id": f"P{pid}",
            "label": label,
            "group": "Paper",
            "title": title,
            "paper_id": pid,
            "score": score_map.get(pid),
        })
        s = score_map.get(pid)
        edge_label = f"{s:.2f}" if isinstance(s, (int, float)) else "命中"
        edges.append({
            "from": "Q",
            "to": f"P{pid}",
            "label": edge_label,
            "arrows": "to",
            "value": s if isinstance(s, (int, float)) else 0.5,  # vis-network 边粗细
        })
    return {"nodes": nodes, "edges": edges}