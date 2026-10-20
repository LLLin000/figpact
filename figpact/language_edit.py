"""Selected-target language preview; one OpenAI-compatible transport, never save.

Authority stays with the live G24 context and existing StyleSession transaction.
Only control metadata (not arrays, images, file paths or credentials) is sent.
"""
from __future__ import annotations

import copy
import json
import os
from urllib import error, parse, request

from .edit_plan import check_plan, request_packet
from .plan_context import discover_overlay

ALLOWED_ROLES = {'axis.title', 'axis.tick', 'curve.linewidth'}


def settings():
    base = os.environ.get('FIGPACT_MODEL_BASE_URL', 'http://127.0.0.1:11434/v1').rstrip('/')
    url = parse.urlsplit(base)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('FIGPACT_MODEL_BASE_URL 必须是无凭据、无查询参数的 HTTP(S) API 根地址')
    return {'base_url': base, 'model': os.environ.get('FIGPACT_MODEL', 'qwen2.5:3b-instruct'),
            'api_key': os.environ.get('FIGPACT_MODEL_API_KEY', '')}


def source_identity(style):
    from . import style_overlay as ov
    dependencies = ov._live_dependencies(ov._import_only(style.script), style.script, style.config)
    return {name: [str(path), digest] for name, (path, digest) in dependencies.items()}


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a local service's API key to a redirect host.


def model_plan(packet, config, control):
    schema = copy.deepcopy(packet['schema'])
    context = packet['input']['context']
    # User selection fixes authority before inference. Decoder constraints cannot
    # grant a new binding; G24 still validates the actual returned object.
    for key in ('scope', 'revision', 'route'):
        schema['properties'][key] = {'type': 'string', 'enum': [context[key]]}
    schema['properties']['edits']['maxItems'] = 1
    schema['properties']['edits']['items']['properties']['control_id']['enum'] = [control['id']]
    payload = {'model': config['model'], 'temperature': 0, 'stream': False,
               'messages': [{'role': 'system', 'content': packet['system']},
                            {'role': 'user', 'content': json.dumps(packet['input'], ensure_ascii=False)}],
               'response_format': {'type': 'json_schema', 'json_schema': {
                   'name': 'selected_style_edit', 'strict': True, 'schema': schema}}}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if config['api_key']:
        headers['Authorization'] = 'Bearer ' + config['api_key']
    req = request.Request(config['base_url'] + '/chat/completions',
                          data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with request.build_opener(_NoRedirect()).open(req, timeout=120) as response:
            raw = response.read(131073)
    except error.HTTPError as exc:
        raise RuntimeError(f'模型服务返回 HTTP {exc.code}；请检查本地模型配置，未生成候选') from None
    except (error.URLError, TimeoutError, OSError):
        raise RuntimeError('无法连接模型服务或调用超时；请启动 Ollama/检查服务端配置，未生成候选') from None
    if len(raw) > 131072:
        raise ValueError('模型响应超过 128 KiB，拒绝处理')
    envelope = json.loads(raw)
    content = envelope['choices'][0]['message']['content']
    if not isinstance(content, str):
        raise ValueError('模型没有返回 JSON 文本计划')
    def invalid_constant(value):
        raise ValueError('非有限 JSON 数值')
    return json.loads(content, parse_constant=invalid_constant)


def preview_selected(style, body, config, expected_source):
    if not isinstance(body, dict) or set(body) != {'frame_revision', 'scene_id', 'target_id', 'request'}:
        return {'status': 'INVALID_LANGUAGE_REQUEST', 'message': '需要当前帧、已点选对象、样式目标和修改要求'}, 400
    text = body['request']
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return {'status': 'INVALID_LANGUAGE_REQUEST', 'message': '修改要求须为 1–2000 字符'}, 400
    frame = style.snapshot()
    if frame['frame_revision'] != body['frame_revision']:
        return {'status': 'STALE_REVISION', 'message': '图帧已变化，请重新点选'}, 409
    if frame.get('style', {}).get('pending'):
        return {'status': 'PENDING_PREVIEW', 'message': '请先确认保存或取消当前预览'}, 409
    target = next((t for t in frame['style']['targets'] if t['target_id'] == body['target_id']), None)
    if target is None or body['scene_id'] not in target['scene_ids']:
        return {'status': 'NO_SELECTED_AUTHORITY', 'message': '所点选对象没有该样式控制权，请重新点选并选择真实目标'}, 400
    try:
        if source_identity(style) != expected_source:
            return {'status': 'STALE_SOURCE', 'message': '来源已变化；请关闭并重新打开图，不复用旧选区'}, 409
        context = discover_overlay(style)
        control = next(c for c in context['controls'] if c['id'] == target['target_id'])
        if control['role'] not in ALLOWED_ROLES:
            return {'status': 'NO_SELECTED_AUTHORITY', 'message': 'v0.1 仅支持授权标题/刻度字号与曲线线宽'}, 400
        context = {**context, 'controls': [control]}
        # No source paths/dependencies or whole-figure data leave the local service.
        visible = {k: context[k] for k in ('scope', 'revision', 'route', 'controls')}
        packet = request_packet(text, visible)
        plan = model_plan(packet, config, control)
        check_plan(plan, context)
        if plan['status'] == 'READY' and (len(plan['edits']) != 1 or plan['edits'][0]['control_id'] != target['target_id']):
            raise ValueError('计划必须只修改用户点选并授权的唯一目标')
        language = {'plan': plan, 'selected_target': target, 'model': config['model'], 'request': text}
        if source_identity(style) != expected_source or style.snapshot()['frame_revision'] != body['frame_revision']:
            return {'status': 'STALE_SOURCE', 'message': '模型调用期间来源或图帧变化，计划已丢弃'}, 409
        if plan['status'] != 'READY':
            return {'status': plan['status'], 'message': plan['reason'], 'language': language}, 200
        result, code = style.preview({'frame_revision': body['frame_revision'],
                                      'target_id': target['target_id'], 'value': plan['edits'][0]['value']})
        return {**result, 'language': language}, code
    except RuntimeError as exc:
        return {'status': 'MODEL_UNAVAILABLE', 'message': str(exc)}, 503
    except (ValueError, KeyError, IndexError, TypeError, StopIteration, OSError):
        return {'status': 'PLAN_REJECTED', 'message': '模型计划或当前控制契约无效；未保存。可重新输入或手动修改数值'}, 422
