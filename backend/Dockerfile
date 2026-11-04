# 백엔드 이미지 (나중에 AWS EC2 등에서 그대로 띄운다). 데이터(SQLite·원본·쪽 이미지)는 /app/data 볼륨에 둔다.
#   docker build -t meetingfee-backend backend/
#   docker run -d --name meetingfee -p 8000:8000 --env-file backend/.env -v meetingfee-data:/app/data meetingfee-backend
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY minutes_review ./minutes_review
COPY rules ./rules
COPY forms ./forms
COPY assets ./assets
COPY tools/team_keys.py ./tools/team_keys.py
COPY tools/hwpkit.py ./tools/hwpkit.py
COPY tools/held_mail.py ./tools/held_mail.py
ENV DATA_DIR=/app/data DATABASE_URL=sqlite:////app/data/app.db DEV_ENDPOINTS=false
VOLUME /app/data
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
