FROM python:3

WORKDIR /scalers

COPY requirements.txt ./
RUN apt update -y && apt install -y ansible sshpass && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV ELASTICSEARCH_HOST="elasticsearch" \
    ELASTICSEARCH_PORT=9200 \
    ELASTICSEARCH_USERNAME="elastic" \
    ELASTICSEARCH_PW="elastic" \
    ELASTICSEARCH_MAX_RESULT=1000000000 \
    RABBITMQ_HOST="rabbitmq" \
    RABBITMQ_MANAGEMENT_PORT=15672 \
    RABBITMQ_OPERATION_PORT=5672 \
    RABBITMQ_QUEUE_NAME_LISTEN="swarm-scaling" \
    RABBITMQ_USERNAME="guest" \
    RABBITMQ_PW="guest" \
    ANSIBLE_SWARM_HOST="192.168.1.1" \
    ANSIBLE_SWARM_USERNAME="root" \
    ANSIBLE_SWARM_PW="root" \
    ANSIBLE_DATA_DIR="/scalers/config/." \
    ANSIBLE_INVENTORY="/scalers/config/hosts"

CMD [ "python", "./run.py" ]