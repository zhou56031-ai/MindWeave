FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/model-cache

WORKDIR /srv/backend

COPY requirements.txt .
RUN python -c "from pathlib import Path; \
lines=Path('requirements.txt').read_text().splitlines(); \
skip=('cuda-', 'cuda_', 'nvidia-', 'nvidia_', 'triton=='); \
Path('/tmp/requirements.cpu.txt').write_text('\n'.join( \
line for line in lines if not line.lstrip().startswith(skip)) + '\n')"
RUN python -m pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    -r /tmp/requirements.cpu.txt

COPY app ./app
COPY main.py ./main.py

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
