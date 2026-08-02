FROM python:3.10-slim-bookworm

WORKDIR /code

COPY ./requirements.txt ./requirements.txt

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN uv pip install --system --no-cache -r requirements.txt

COPY ./src ./src

CMD ["streamlit", "run", "src/app.py", "--server.address=0.0.0.0", "--server.port=8501"]