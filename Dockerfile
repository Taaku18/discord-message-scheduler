FROM python:3.10-slim as py

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv

RUN apt-get update && \
    apt-get install -y --no-install-recommends g++ && \
    rm -rf /var/lib/apt/lists/*

FROM py as build

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git && \
    curl -sSL https://raw.githubusercontent.com/pdm-project/pdm/main/install-pdm.py | python3 -

RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY pyproject.toml pdm.lock /
RUN $HOME/.local/bin/pdm install --prod -G speed --no-lock --no-editable

FROM py

ENV PATH "$VIRTUAL_ENV/bin:$PATH"
COPY --from=build /opt/venv /opt/venv

WORKDIR /bot
CMD ["python", "start.py"]
COPY . /bot
