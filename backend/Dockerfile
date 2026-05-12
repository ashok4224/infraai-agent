FROM python:3.12-slim

# Install JDK (headless) + unzip + curl for SQLcl
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless unzip curl && \
    rm -rf /var/lib/apt/lists/*

# Install Oracle SQLcl (latest — has native MCP support)
RUN curl -fSL "https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip" \
      -o /tmp/sqlcl.zip && \
    unzip -q /tmp/sqlcl.zip -d /opt && \
    rm /tmp/sqlcl.zip && \
    chmod +x /opt/sqlcl/bin/sql
ENV PATH="/opt/sqlcl/bin:${PATH}"
ENV SQLCL_HOME="/opt/sqlcl"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd --create-home appuser
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
