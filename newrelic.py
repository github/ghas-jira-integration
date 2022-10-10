import asyncio
import os
import httpx
import structlog
from datetime import datetime
from structlog import get_logger
import logging
from json import dumps

logger = logging.getLogger(__name__)
log = get_logger("Structured Logger")


# Custom processor
# Uses the New Relic Log API
# https://docs.newrelic.com/docs/logs/log-management/log-api/introduction-log-api/
async def send_to_newrelic(event_dict):
    logger.info(
        'Got {event_dict}" '.format(
            event_dict=event_dict
        )
    )
    # Your New Relic API Key
    # https://docs.newrelic.com/docs/apis/intro-apis/new-relic-api-keys/
    headers = {"Api-Key": os.environ["NEWRELIC-API_KEY"]}

    # Our log message and all the event context is sent as a JSON string
    # in the POST body
    # https://docs.newrelic.com/docs/logs/log-management/log-api/introduction-log-api/#json-content
    payload = {
        "message": f"{event_dict['event']}",
        "attributes": event_dict,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://log-api.newrelic.com/log/v1", json=payload, headers=headers)
    except httpx.RequestError as err:
        logger.error(
            'Error "Creating request for {url} {error}" '.format(
                url=err.request.url,
                error=err
            )
        )
    except httpx.HTTPStatusError as err:
        logger.error(
            'Error "Status code of {statusCode} received for {url}" '.format(
                url=err.request.url,
                statusCode=err.response.status_code
            )
        )
    except httpx.HTTPError as err:
        logger.error(
            'Error "HTTP Exception for {url} - {err}" '.format(
                url=err.request.url,
                err=err
            )
        )
    except BaseException as err:
        logger.error(
            'Error "Other Exception - {err}" '.format(
                err=err
            )
        )


# Configure Structlog's processor pipeline
structlog.configure(
    processors=[send_to_newrelic, structlog.processors.JSONRenderer()],
)

class CustomEvent(object):
    "This class is used to represent any custom notice we want sent without any data"
    def __init__(self, event):
        self.event = event

    def log(self):
        return self.__dict__

    def send(self):
        asyncio.run(send_to_newrelic(self.log()))

class HTTPCallLog(object):
    "This class represents a HTTP call"
    def __init__(self, event):
        self.start_time = str(datetime.utcnow())
        self.end_time = ""
        self.duration = ""
        self.response = ""
        self.status_code = ""
        self.error = ""
        self.event = event
        self.success = ""

#2015-02-17 23:58:44.76100
    def successful(self, response, status_code=200):
        self.end_time = str(datetime.utcnow())
        duration = datetime.strptime(self.end_time,  '%Y-%m-%d %H:%M:%S.%f') - datetime.strptime(self.start_time, '%Y-%m-%d %H:%M:%S.%f')
        self.duration = duration.total_seconds() * 1000
        self.status_code = status_code
        self.response = str(response)
        self.event = self.event
        self.success = True
        self._send()

    def failure(self, response, status_code, error):
        self.end_time = str(datetime.utcnow())
        duration = datetime.strptime(self.end_time,  '%Y-%m-%d %H:%M:%S.%f') - datetime.strptime(self.start_time, '%Y-%m-%d %H:%M:%S.%f')
        self.duration = duration.total_seconds() * 1000
        self.status_code = status_code
        self.response = str(response)
        self.event = self.event
        self.success = False
        self._send()

    def log(self):
        return self.__dict__

    def _send(self):
        asyncio.run(send_to_newrelic(self.log()))


