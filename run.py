from ansible_runner import run
from datetime import datetime, timedelta
from elasticsearch import Elasticsearch
from json import dumps, loads
from logging import info, warning, error, critical, basicConfig, INFO
from os import getenv, _exit
from pika import BlockingConnection, PlainCredentials, ConnectionParameters
from requests import get
from shutil import rmtree
from sys import exit
from time import sleep
from uuid import uuid4


basicConfig(format=dumps({
    'datetime': '%(asctime)s',
    'loglevel': '[%(levelname)s]',
    'message': '%(message)s'
}), datefmt='%H:%M:%S %d/%m/%Y', level=INFO)

ELASTICSEARCH_HOST         = getenv(key='ELASTICSEARCH_HOST')
ELASTICSEARCH_PORT         = getenv(key='ELASTICSEARCH_PORT')
ELASTICSEARCH_USERNAME     = getenv(key='ELASTICSEARCH_USERNAME')
ELASTICSEARCH_PW           = getenv(key='ELASTICSEARCH_PW')
ELASTICSEARCH_MAX_RESULT   = getenv(key='ELASTICSEARCH_MAX_RESULT')

RABBITMQ_HOST              = getenv(key='RABBITMQ_HOST')
RABBITMQ_MANAGEMENT_PORT   = getenv(key='RABBITMQ_MANAGEMENT_PORT')
RABBITMQ_OPERATION_PORT    = getenv(key='RABBITMQ_OPERATION_PORT')
RABBITMQ_QUEUE_NAME_LISTEN = getenv(key='RABBITMQ_QUEUE_NAME_LISTEN')
RABBITMQ_USERNAME          = getenv(key='RABBITMQ_USERNAME')
RABBITMQ_PASSWORD          = getenv(key='RABBITMQ_PW')

ANSIBLE_SWARM_HOST         = getenv(key='ANSIBLE_SWARM_HOST')
ANSIBLE_SWARM_USERNAME     = getenv(key='ANSIBLE_SWARM_USERNAME')
ANSIBLE_SWARM_PASSWORD     = getenv(key='ANSIBLE_SWARM_PW')
ANSIBLE_DATA_DIR           = getenv(key='ANSIBLE_DATA_DIR')
ANSIBLE_INVENTORY          = getenv(key='ANSIBLE_INVENTORY')

def main():
    elasticsearch_response = connect_elasticsearch()
    if check_env() is False or elasticsearch_response is False or check_rabbitmq() is False:
        return
    processor(elasticsearch_response=elasticsearch_response)


def check_env():
    info(msg='Checking environment variables...')
    env_vars = {
        'ELASTICSEARCH_HOST': ELASTICSEARCH_HOST,
        'ELASTICSEARCH_PORT': ELASTICSEARCH_PORT,
        'ELASTICSEARCH_USERNAME': ELASTICSEARCH_USERNAME,
        'ELASTICSEARCH_PW': ELASTICSEARCH_PW,
        'ELASTICSEARCH_MAX_RESULT': ELASTICSEARCH_MAX_RESULT,
        'RABBITMQ_HOST': RABBITMQ_HOST,
        'RABBITMQ_MANAGEMENT_PORT': RABBITMQ_MANAGEMENT_PORT,
        'RABBITMQ_OPERATION_PORT': RABBITMQ_OPERATION_PORT,
        'RABBITMQ_QUEUE_NAME_LISTEN': RABBITMQ_QUEUE_NAME_LISTEN,
        'RABBITMQ_USERNAME': RABBITMQ_USERNAME,
        'RABBITMQ_PW': RABBITMQ_PASSWORD,
        'ANSIBLE_SWARM_HOST': ANSIBLE_SWARM_HOST,
        'ANSIBLE_SWARM_USERNAME': ANSIBLE_SWARM_USERNAME,
        'ANSIBLE_SWARM_PASSWORD': ANSIBLE_SWARM_PASSWORD,
        'ANSIBLE_DATA_DIR': ANSIBLE_DATA_DIR,
        'ANSIBLE_INVENTORY': ANSIBLE_INVENTORY
    }
    if not all([value for _, value in env_vars.items()]):
        error(msg=f'Missing required variables: {[key for key, value in env_vars.items() if not value]}')
        return False
    info(msg='Environment variables [OK]')
    return True


def connect_elasticsearch():
    info(msg='Checking Elasticsearch...')
    try:
        elasticsearch_response = Elasticsearch(
            hosts=f'http://{ELASTICSEARCH_HOST}:{ELASTICSEARCH_PORT}', 
            basic_auth=(ELASTICSEARCH_USERNAME, ELASTICSEARCH_PW)
        )
    except ValueError as error_exception:
        error(msg=str(error_exception))
        return False
    while True:
        if elasticsearch_response.ping() is False:
            warning(msg='Ping to Elasticsearch fail, re-ping after 5 seconds')
            sleep(5)
        else:
            break
    info(msg='Elasticsearch [OK]')
    index_settings = {
        "settings": {
            "index": {
                "max_result_window": int(ELASTICSEARCH_MAX_RESULT)
            }
        }
    }
    info(msg='Checking "responser-swarm" index...')
    if not elasticsearch_response.indices.exists(index='responser-swarm'):
        info(msg='Creating "responser-swarm"')
        elasticsearch_response.indices.create(index="responser-swarm", body=index_settings)
        info(msg='Created "responser-swarm"')
    info(msg='"responser-swarm" [OK]')
    info(msg='Checking "responser-swarm-executions" index...')
    if not elasticsearch_response.indices.exists(index='responser-swarm-executions'):
        info(msg='Creating "responser-swarm-executions"')
        elasticsearch_response.indices.create(index="responser-swarm-executions", body=index_settings)
        info(msg='Created "responser-swarm-executions"')
    info(msg='"responser-swarm-executions" [OK]')
    info(msg='Checking "responser-swarm-errorlogs" index...')
    if not elasticsearch_response.indices.exists(index='responser-swarm-errorlogs'):
        info(msg='Creating "responser-swarm-errorlogs"')
        elasticsearch_response.indices.create(index="responser-swarm-errorlogs", body=index_settings)
        info(msg='Created "responser-swarm-errorlogs"')
    info(msg='"responser-swarm-errorlogs" [OK]')
    return elasticsearch_response


def check_rabbitmq():
    info(msg='Checking RabbitMQ...')
    try:
        rabbitmq_response = get(
            url=f'http://{RABBITMQ_HOST}:{RABBITMQ_MANAGEMENT_PORT}/api/healthchecks/node', 
            auth=(RABBITMQ_USERNAME, RABBITMQ_PASSWORD)
        )
        if rabbitmq_response.status_code != 200:
            error(msg=f'RabbitMQ connection testing fail, status code {rabbitmq_response.status_code}')
            return False
    except:
        error(msg='Can\'t perform GET request to RabbitMQ, fail for connection testing')
        return False
    info(msg='RabbitMQ [OK]')
    return True


def processor(elasticsearch_response: Elasticsearch):
    connection = BlockingConnection(
        ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_OPERATION_PORT,
            credentials=PlainCredentials(
                username=RABBITMQ_USERNAME,
                password=RABBITMQ_PASSWORD
            )
        )
    )
    channel = connection.channel()
    channel.queue_declare(queue=RABBITMQ_QUEUE_NAME_LISTEN, durable=True)
    def callback(ch, method, properties, body: bytes):
        request_body: dict = loads(body.decode())
        responser_name = request_body.get('real_name')
        service_name = request_body.get('service_name')
        extra_vars = {
            'username_swarm_node': ANSIBLE_SWARM_USERNAME,
            'password_swarm_node': ANSIBLE_SWARM_PASSWORD,
            'service_name': service_name
        }
        playbook = f'{ANSIBLE_DATA_DIR}/playbooks/ansible_scaling_swarm_playbook.yaml'
        if request_body.get('scaling') == 'up':
            extra_vars['replicas'] = request_body.get('replicas')
            if request_body.get('timer') is True:
                playbook = f'{ANSIBLE_DATA_DIR}/playbooks/ansible_scaling_with_timer_playbook.yaml'
                extra_vars['timer'] = request_body.get('auto_down_after_minutes')
        if request_body.get('scaling') == 'down':
            extra_vars['replicas'] = request_body.get('replicas')
        unique_id = uuid4()
        runner = run(
            private_data_dir=ANSIBLE_DATA_DIR,
            playbook=playbook,
            inventory=ANSIBLE_INVENTORY,
            host_pattern='swarm',
            json_mode=True,
            quiet=True,
            ident=unique_id,
            extravars=extra_vars
        )
        errorlogs = None
        is_error = False
        for event in runner.events:
            if event.get('event') == 'runner_on_unreachable':
                errorlogs = event['stdout']
                break
            if event.get('event') == 'runner_on_failed':
                errorlogs = event['stdout']
                break
        if runner.status == 'failed':
            elasticsearch_response.index(index='responser-swarm-errorlogs', document={
                'responser_name': responser_name,
                'message': errorlogs,
                'pattern': 'ansible_playbook'
            })
            print('error roi')
            critical(msg=dumps(errorlogs))
            is_error = True
        time_now = int(datetime.now().timestamp())
        if is_error is True:
            elasticsearch_response.update(
                index='responser-swarm-executions',
                id=request_body.get('execution_id'),
                refresh='wait_for',
                doc={
                    'last_action': 'error',
                    'last_logs': errorlogs,
                }
            )
        else:
            elasticsearch_response.update(
                index='responser-swarm-executions',
                id=request_body.get('execution_id'),
                refresh='wait_for',
                doc={
                    'status': request_body.get('scaling'),
                    'at_time': time_now,
                    'replicas': request_body.get('replicas'),
                    'last_action': 'success',
                    'last_logs': None,
                    'timer': request_body.get('timer')
                }
            )
            elasticsearch_response.update(
                index='responser-swarm',
                id=request_body.get('swarm_id'),
                refresh='wait_for',
                doc={
                    'current_nums': request_body.get('replicas')
                }
            )
        print(request_body)
        rmtree(path=f'{ANSIBLE_DATA_DIR}/artifacts/{unique_id}', ignore_errors=True)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=RABBITMQ_QUEUE_NAME_LISTEN, on_message_callback=callback)
    channel.start_consuming()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        try:
            exit(0)
        except SystemExit:
            _exit(0)