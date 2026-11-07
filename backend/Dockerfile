# 与 pyrightconfig.json 的 pythonVersion、CI 的 setup-python、线上 venv 对齐（都是 3.12）。
# 之前写 3.11 是历史遗留：CI 也是 3.11，但 pyright 按 3.12 检查，三方标准不一致。
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
