FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY frontend ./frontend
COPY data ./data
RUN useradd -r -u 10001 appuser && mkdir /data && chown appuser /data
USER appuser
ENV CREDITLENS_DB=/data/creditlens.db \
    CREDITLENS_FRONTEND=/srv/frontend \
    CREDITLENS_ENV=production
VOLUME /data
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u;u.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
