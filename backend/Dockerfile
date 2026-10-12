FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY backend/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY backend/app /srv/app
COPY knowledge /srv/knowledge
COPY scripts /srv/scripts
RUN addgroup --system app && adduser --system --ingroup app app && mkdir /appdata && chown app:app /appdata
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
