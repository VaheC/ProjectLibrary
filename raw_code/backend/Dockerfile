FROM python:3.10-slim-bookworm

WORKDIR /code

COPY ./requirements.txt ./requirements.txt

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
# RUN pip install uv

# RUN pip install --no-cache-dir -r ./requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt

COPY ./src ./src

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]