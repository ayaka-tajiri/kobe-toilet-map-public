# -*- coding: utf-8 -*-

# This is a simple Hello World Alexa Skill, built using
# the implementation of handler classes approach in skill builder.
import logging
import json
import math
import urllib.request
import urllib.parse

from operator import itemgetter
from boto3.session import Session
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_core.handler_input import HandlerInput

from ask_sdk_model.ui import SimpleCard, AskForPermissionsConsentCard
from ask_sdk_model import Response
from ask_sdk_model.interfaces.alexa.presentation.apl import (
    RenderDocumentDirective)

sb = SkillBuilder()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

region = "ap-northeast-1"
session = Session(
    region_name=region
)
dynamodb = session.resource('dynamodb')

table = dynamodb.Table('toilet-map-kobe-Table1-14PAVSC6LQ5B7')


def _load_apl_document(file_path):
    # type: (str) -> Dict[str, Any]
    """Load the apl json document at the path into a dict object."""
    with open(file_path) as f:
        return json.load(f)


def distance(latitude1, longitude1, latitude2, longitude2, mode=1):
    radians_latitude1 = math.radians(latitude1)
    radians_longitude1 = math.radians(longitude1)
    radians_latitude2 = math.radians(latitude2)
    radians_longitude2 = math.radians(longitude2)

    diff_latitude = radians_latitude1 - radians_latitude2
    diff_longitude = radians_longitude1 - radians_longitude2

    average_latitude = (radians_latitude1 + 0) / 2.0

    a = 6378137.0 if mode else 6377397.155  # 赤道半径
    b = 6356752.314140356 if mode else 6356078.963  # 極半径
    # $e2 = ($a * $a - $b * $b) / ($a * $a);
    e2 = 0.00669438002301188 if mode else 0.00667436061028297  # 第一離心率 ^ 2
    # $a1e2 = $a * (1 - $e2);
    a1e2 = 6335439.32708317 if mode else 6334832.10663254  # 赤道上の子午線曲率半径

    sin_latitude = math.sin(average_latitude)
    w2 = 1.0 - e2 * (sin_latitude * sin_latitude)
    m = a1e2 / (math.sqrt(w2) * w2)  # 子午線曲率半径M
    n = a / math.sqrt(w2)  # 卯酉線曲率半径

    t1 = m * diff_latitude
    t2 = n * math.cos(average_latitude) * diff_longitude
    dist = math.sqrt((t1 * t1) + (t2 * t2))

    return dist


class LaunchRequestHandler(AbstractRequestHandler):
    """Handler for Skill Launch."""

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        is_geo_supported = handler_input.request_envelope.context.system.device.supported_interfaces.geolocation

        if is_geo_supported:
            speech_text = "このスキルでは神戸市内のトイレの場所を案内します。近くのトイレを探すときは「近くのトイレを調べる」と言ってください。" \
                          "場所を指定して調べるときは「場所を指定して調べる」と言ってください。トイレの音を流す場合は「音を流す」と言ってください。"
        else:
            speech_text = "このスキルでは神戸市内のトイレの場所を案内します。続ける場合は「トイレを調べる」と言ってください。" \
                          "トイレの音を流す場合は「音を流す」と言ってください。"

        handler_input.response_builder.speak(speech_text).set_card(
            SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(False)

        return handler_input.response_builder.response


class CurrentToiletIntentHandler(AbstractRequestHandler):
    """Handler for Hello World Intent."""

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("CurrentToiletIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        attr = handler_input.attributes_manager.session_attributes
        attr["status"] = "can_next"

        is_geo_supported = handler_input.request_envelope.context.system.device.supported_interfaces.geolocation
        id_apl_supported = \
            handler_input.request_envelope.context.system.device.supported_interfaces.alexa_presentation_apl
        geolocation = handler_input.request_envelope.context.geolocation

        # 位置情報が使えない端末の場合はreturn
        if not is_geo_supported:
            speech_text = "この端末では位置情報が使用できません。「トイレを調べる」と言って、特定の場所付近のトイレを探してください。"
            handler_input.response_builder.speak(speech_text).set_card(
                SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                False)
            return handler_input.response_builder.response

        # スキルの位置情報が有効になっていない場合はreturn
        if not geolocation or not geolocation.coordinate:
            speech_text = "お客様の位置情報を使用します。位置情報の共有を有効にするには、Alexaアプリに移動し、指示に従って操作してください。"
            handler_input.response_builder.speak(speech_text).set_card(
                AskForPermissionsConsentCard(["alexa::devices:all:geolocation:read"])).set_should_end_session(
                True)
            return handler_input.response_builder.response

        # 緯度と経度を取得、もっとも近いトイレを検索する
        # DBから値を取得
        table_list = table.scan()

        current_latitude = handler_input.request_envelope.context.geolocation.coordinate.latitude_in_degrees
        current_longitude = handler_input.request_envelope.context.geolocation.coordinate.longitude_in_degrees

        attr["current_latitude"] = current_latitude
        attr["current_longitude"] = current_longitude

        # min_distanceに一番上の施設までの距離を入れる
        near_toilet_items = []
        for item in table_list['Items']:
            toilet_distance = distance(current_latitude, current_longitude, float(item['latitude']),
                                       float(item['longitude']))
            item.update({"distance": toilet_distance})
            near_toilet_items.append(item)

        near_toilet_items.sort(key=itemgetter('distance'))
        nearest_toilet_items = near_toilet_items[0:10]
        attr["nearest_toilet_items"] = nearest_toilet_items
        current_toilet_number = 0
        attr["current_toilet_number"] = current_toilet_number

        speech_text = "近くのトイレは" + nearest_toilet_items[current_toilet_number]['facility'] + "です。" + "距離は" + str(
            round(nearest_toilet_items[current_toilet_number]['distance'])) + "メートルです。" + "このトイレには" + \
                      nearest_toilet_items[current_toilet_number][
                          'seat'] + "があります。次に近いトイレを探す場合は「次」、終了する場合は「終了」と言ってください。"

        url_little = "https://maps.googleapis.com/maps/api/staticmap?size=300x200&scale=2&markers=color:red%7C" + str(
            current_latitude) + "," + str(current_longitude) + "&markers=color:blue%7Clabel:T%7C" + str(
            nearest_toilet_items[current_toilet_number]['latitude']) + "," + str(
            nearest_toilet_items[current_toilet_number]['longitude']) + "&key=[YOUR_API_KEY]"

        url_big = "https://maps.googleapis.com/maps/api/staticmap?size=600x300&scale=2&markers=color:red%7C" + str(
            current_latitude) + "," + str(current_longitude) + "&markers=color:blue%7Clabel:T%7C" + str(
            nearest_toilet_items[current_toilet_number]['latitude']) + "," + str(
            nearest_toilet_items[current_toilet_number]['longitude']) + "&key=[YOUR_API_KEY]"

        logger.info("url_little: " + url_little)
        logger.info("url_big: " + url_big)

        if id_apl_supported:
            handler_input.response_builder.speak(speech_text).set_card(
                SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                False).add_directive(
                RenderDocumentDirective(
                    document=_load_apl_document("document/devices.json"),
                    datasources={
                        "bodyTemplate7Data": {
                            "type": "object",
                            "objectId": "bt7Sample",
                            "title": "神戸のトイレマップ",
                            "image": {
                                "contentDescription": None,
                                "smallSourceUrl": None,
                                "largeSourceUrl": None,
                                "sources": [
                                    {
                                        "url": url_little,
                                        "size": "small",
                                        "widthPixels": 0,
                                        "heightPixels": 0
                                    },
                                    {
                                        "url": url_big,
                                        "size": "large",
                                        "widthPixels": 0,
                                        "heightPixels": 0
                                    }
                                ]
                            },
                            "logoUrl": "https://2.bp.blogspot.com/-2qe2liteaS8/VOxOHvOk8pI/AAAAAAAAr5A/40EPCqlqmso/s400/toilet_benki.png"
                        }
                    }
                )
            )
        else:
            handler_input.response_builder.speak(speech_text).set_card(
                SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                False)
        return handler_input.response_builder.response


class SpecificToiletIntentHandler(AbstractRequestHandler):
    """Handler for Hello World Intent."""

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("SpecificToiletIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        attr = handler_input.attributes_manager.session_attributes
        attr["status"] = "can_next"

        id_apl_supported = \
            handler_input.request_envelope.context.system.device.supported_interfaces.alexa_presentation_apl
        location = handler_input.request_envelope.request.intent.slots['address'].value

        url = 'https://maps.googleapis.com/maps/api/place/findplacefromtext/json?input=' \
              + urllib.parse.quote(location) \
              + '&inputtype=textquery&fields=name,geometry&key=[YOUR_API_KEY]'
        logger.info('url: ' + url)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as res:
            body = json.load(res)

        if len(body['candidates']) < 1:
            speech_text = '場所が見つかりませんでした。'
            handler_input.response_builder.speak(speech_text).set_should_end_session(
                True)
            return handler_input.response_builder.response

        # DBから値を取得
        table_list = table.scan()
        latitude = body['candidates'][0]['geometry']['location']['lat']
        longitude = body['candidates'][0]['geometry']['location']['lng']

        attr["current_latitude"] = latitude
        attr["current_longitude"] = longitude

        # min_distanceに一番上の施設までの距離を入れる
        near_toilet_items = []
        for item in table_list['Items']:
            toilet_distance = distance(latitude, longitude, float(item['latitude']), float(item['longitude']))
            item.update({"distance": toilet_distance})
            near_toilet_items.append(item)

        near_toilet_items.sort(key=itemgetter('distance'))
        nearest_toilet_items = near_toilet_items[0:10]
        attr["nearest_toilet_items"] = nearest_toilet_items
        current_toilet_number = 0
        attr["current_toilet_number"] = current_toilet_number

        speech_text = "近くのトイレは" + nearest_toilet_items[current_toilet_number]['facility'] + "です。" + "距離は" \
                      + str(round(nearest_toilet_items[current_toilet_number]['distance'])) + "メートルです。" + "このトイレには" \
                      + nearest_toilet_items[current_toilet_number]['seat'] \
                      + "があります。次に近いトイレを探す場合は「次」、終了する場合は「終了」と言ってください。"

        url_little = "https://maps.googleapis.com/maps/api/staticmap?size=300x200&scale=2&markers=color:red%7C" + str(
            latitude) + "," + str(longitude) + "&markers=color:blue%7Clabel:T%7C" + str(
            nearest_toilet_items[current_toilet_number]['latitude']) + "," + str(
            nearest_toilet_items[current_toilet_number]['longitude']) + "&key=[YOUR_API_KEY]"

        url_big = "https://maps.googleapis.com/maps/api/staticmap?size=600x300&scale=2&markers=color:red%7C" + str(
            latitude) + "," + str(longitude) + "&markers=color:blue%7Clabel:T%7C" + str(
            nearest_toilet_items[current_toilet_number]['latitude']) + "," + str(
            nearest_toilet_items[current_toilet_number]['longitude']) + "&key=[YOUR_API_KEY]"

        logger.info("url_little: " + url_little)
        logger.info("url_big: " + url_big)

        if id_apl_supported:
            handler_input.response_builder.speak(speech_text).set_card(
                SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                False).add_directive(
                RenderDocumentDirective(
                    document=_load_apl_document("document/devices.json"),
                    datasources={
                        "bodyTemplate7Data": {
                            "type": "object",
                            "objectId": "bt7Sample",
                            "title": "神戸のトイレマップ",
                            "image": {
                                "contentDescription": None,
                                "smallSourceUrl": None,
                                "largeSourceUrl": None,
                                "sources": [
                                    {
                                        "url": url_little,
                                        "size": "small",
                                        "widthPixels": 0,
                                        "heightPixels": 0
                                    },
                                    {
                                        "url": url_big,
                                        "size": "large",
                                        "widthPixels": 0,
                                        "heightPixels": 0
                                    }
                                ]
                            },
                            "logoUrl": "https://2.bp.blogspot.com/-2qe2liteaS8/VOxOHvOk8pI/AAAAAAAAr5A/40EPCqlqmso/s400/toilet_benki.png"
                        }
                    }
                )
            )
        else:
            handler_input.response_builder.speak(speech_text).set_card(
                SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                False)
        return handler_input.response_builder.response


class NextIntentHandler(AbstractRequestHandler):

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        attr = handler_input.attributes_manager.session_attributes
        return is_intent_name("AMAZON.NextIntent")(handler_input) and (attr.get("status") == "can_next")

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        attr = handler_input.attributes_manager.session_attributes
        id_apl_supported = \
            handler_input.request_envelope.context.system.device.supported_interfaces.alexa_presentation_apl

        nearest_toilet_items = attr.get("nearest_toilet_items")
        current_toilet_number = attr.get("current_toilet_number")
        current_toilet_number = current_toilet_number + 1
        attr["current_toilet_number"] = current_toilet_number

        url_little = "https://maps.googleapis.com/maps/api/staticmap?size=300x200&scale=2&markers=color:red%7C" + str(
            attr.get("current_latitude")) + "," + str(
            attr.get(
                "current_longitude")) + "&markers=color:blue%7Clabel:T%7C" + str(
            nearest_toilet_items[current_toilet_number]['latitude']) + "," + str(
            nearest_toilet_items[current_toilet_number][
                'longitude']) + "&key=[YOUR_API_KEY]"

        url_big = "https://maps.googleapis.com/maps/api/staticmap?size=600x300&scale=2&markers=color:red%7C" + str(
            attr.get("current_latitude")) + "," + str(
            attr.get(
                "current_longitude")) + "&markers=color:blue%7Clabel:T%7C" + str(
            nearest_toilet_items[current_toilet_number]['latitude']) + "," + str(
            nearest_toilet_items[current_toilet_number][
                'longitude']) + "&key=[YOUR_API_KEY]"

        logger.info("url_little: " + url_little)
        logger.info("url_big: " + url_big)

        if current_toilet_number < 9:
            speech_text = "近くのトイレは" + nearest_toilet_items[current_toilet_number]['facility'] + "です。" + "距離は" \
                          + str(round(nearest_toilet_items[current_toilet_number]['distance'])) + "メートルです。" \
                          + "このトイレには" + nearest_toilet_items[current_toilet_number]['seat'] \
                          + "があります。次に近いトイレを探す場合は「次」、終了する場合は「終了」と言ってください。"

            if id_apl_supported:
                handler_input.response_builder.speak(speech_text).set_card(
                    SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                    False).add_directive(
                    RenderDocumentDirective(
                        document=_load_apl_document("document/devices.json"),
                        datasources={
                            "bodyTemplate7Data": {
                                "type": "object",
                                "objectId": "bt7Sample",
                                "title": "神戸のトイレマップ",
                                "image": {
                                    "contentDescription": None,
                                    "smallSourceUrl": None,
                                    "largeSourceUrl": None,
                                    "sources": [
                                        {
                                            "url": url_little,
                                            "size": "small",
                                            "widthPixels": 0,
                                            "heightPixels": 0
                                        },
                                        {
                                            "url": url_big,
                                            "size": "large",
                                            "widthPixels": 0,
                                            "heightPixels": 0
                                        }
                                    ]
                                },
                                "logoUrl": "https://2.bp.blogspot.com/-2qe2liteaS8/VOxOHvOk8pI/AAAAAAAAr5A/40EPCqlqmso/s400/toilet_benki.png"
                            }
                        }
                    )
                )
            else:
                handler_input.response_builder.speak(speech_text).set_card(
                    SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                    False)
        else:
            speech_text = "近くのトイレは" + nearest_toilet_items[current_toilet_number]['facility'] + "です。" + "距離は" \
                          + str(round(nearest_toilet_items[current_toilet_number]['distance'])) + "メートルです。" \
                          + "このトイレには" + nearest_toilet_items[current_toilet_number]['seat'] \
                          + "があります。"
            attr["status"] = "end"

            if id_apl_supported:
                handler_input.response_builder.speak(speech_text).set_card(
                    SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                    True).add_directive(
                    RenderDocumentDirective(
                        document=_load_apl_document("document/devices.json"),
                        datasources={
                            "bodyTemplate7Data": {
                                "type": "object",
                                "objectId": "bt7Sample",
                                "title": "神戸のトイレマップ",
                                "image": {
                                    "contentDescription": None,
                                    "smallSourceUrl": None,
                                    "largeSourceUrl": None,
                                    "sources": [
                                        {
                                            "url": url_little,
                                            "size": "small",
                                            "widthPixels": 0,
                                            "heightPixels": 0
                                        },
                                        {
                                            "url": url_big,
                                            "size": "large",
                                            "widthPixels": 0,
                                            "heightPixels": 0
                                        }
                                    ]
                                },
                                "logoUrl": "https://2.bp.blogspot.com/-2qe2liteaS8/VOxOHvOk8pI/AAAAAAAAr5A/40EPCqlqmso/s400/toilet_benki.png"
                            }
                        }
                    )
                )
            else:
                handler_input.response_builder.speak(speech_text).set_card(
                    SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
                    True)

        return handler_input.response_builder.response


class SoundToiletIntentHandler(AbstractRequestHandler):

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("SoundToiletIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        speech_text = "<speak><audio src='soundbank://soundlibrary/nature/amzn_sfx_stream_03'/>" \
                      "<audio src='soundbank://soundlibrary/nature/amzn_sfx_stream_03'/>" \
                      "<audio src='soundbank://soundlibrary/nature/amzn_sfx_stream_03'/>" \
                      "<audio src='soundbank://soundlibrary/nature/amzn_sfx_stream_03'/>" \
                      "<audio src='soundbank://soundlibrary/nature/amzn_sfx_stream_03'/></speak>"

        handler_input.response_builder.speak(speech_text).speak(
            speech_text).set_should_end_session(
            True)
        return handler_input.response_builder.response


class HelpIntentHandler(AbstractRequestHandler):
    """Handler for Help Intent."""

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = "このスキルでは神戸にあるトイレの場所を教えてくれます。トイレを調べる場合は「トイレを調べる」、終了する場合は「終了」と言ってください。"

        handler_input.response_builder.speak(speech_text).ask(
            speech_text).set_card(SimpleCard("神戸のトイレマップ", speech_text))
        return handler_input.response_builder.response


class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Single handler for Cancel and Stop Intent."""

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.CancelIntent")(handler_input) or
                is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = ""

        handler_input.response_builder.speak(speech_text).set_card(
            SimpleCard("神戸のトイレマップ", speech_text)).set_should_end_session(
            True)
        return handler_input.response_builder.response


class FallbackIntentHandler(AbstractRequestHandler):
    """AMAZON.FallbackIntent is only available in en-US locale.
    This handler will not be triggered except in that locale,
    so it is safe to deploy on any locale.
    """

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = (
            "このスキルでは神戸にあるトイレの場所を教えてくれます。トイレを調べる場合は「トイレを調べる」、終了する場合は「終了」と言ってください。")
        reprompt = "トイレを調べる場合は「トイレを調べる」、終了する場合は「終了」と言ってください。"
        handler_input.response_builder.speak(speech_text).ask(reprompt)
        return handler_input.response_builder.response


class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler for Session End."""

    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        return handler_input.response_builder.set_should_end_session(
            True).response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Catch all exception handler, log exception and
    respond with custom message.
    """

    def can_handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> bool
        return True

    def handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> Response
        logger.error(exception, exc_info=True)

        speech_text = "問題が発生しました。もう一度初めから試してください。"

        return handler_input.response_builder.speak(speech_text).set_should_end_session(
            True).response


sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(CurrentToiletIntentHandler())
sb.add_request_handler(SpecificToiletIntentHandler())
sb.add_request_handler(NextIntentHandler())
sb.add_request_handler(SoundToiletIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())

sb.add_exception_handler(CatchAllExceptionHandler())

handler = sb.lambda_handler()
