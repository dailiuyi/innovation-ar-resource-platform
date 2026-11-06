"""Authoring source for the 4DGS Scene Resource API (administrator and anonymous client sides)."""
from pathlib import Path
import copy
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]

def obj(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}

def string(**kw): return dict(type='string', **kw)
def integer(**kw): return dict(type='integer', **kw)
def enum(*values): return string(enum=list(values))
def array(items, **kw): return dict(type='array', items=items, **kw)
def ref(name): return {'$ref': '#/components/schemas/' + name}

uuid = string(format='uuid')
sha = string(pattern='^[0-9a-f]{64}$')
timestamp = string(format='date-time')
int64 = integer(format='int64', minimum=0)

file_status = enum('PENDING', 'UPLOADING', 'AVAILABLE', 'FAILED')
upload_status = enum('PENDING', 'UPLOADING', 'FAILED', 'READY', 'DELETING', 'DELETE_FAILED')
schemas = {
    'Error': obj({'code': string(pattern='^AR_[0-9]{3}$'), 'message': string(), 'traceId': string()}),
    'FrameworkResponse': {'type': 'object', 'additionalProperties': True, 'properties': {'code': integer(), 'msg': string()}},
    'Login': obj({'username': string(), 'password': string(minLength=6, maxLength=64)}),
    'AccountCreate': obj({'userName': string(pattern='^[A-Za-z0-9_]{3,30}$'), 'nickName': string(minLength=1, maxLength=30),
                          'password': string(minLength=6, maxLength=64)}),
    'AccountStatus': obj({'userId': integer(format='int64'), 'status': enum('0', '1')}),
    'AccountPassword': obj({'userId': integer(format='int64'), 'password': string(minLength=6, maxLength=64)}),
    'OwnPassword': obj({'oldPassword': string(), 'newPassword': string(minLength=6, maxLength=64)}),
    'ProfileUpdate': obj({'nickName': string(maxLength=30), 'email': string(maxLength=50),
                          'phonenumber': string(maxLength=11), 'sex': enum('0', '1', '2')}, []),
    'EnabledUpdate': obj({'enabled': {'type': 'boolean'}, 'expectedVersion': integer(minimum=0),
                          'reason': string(minLength=1)}),
    'AuditList': obj({'items': array({'type': 'object', 'additionalProperties': True}), 'total': integer(minimum=0)}),
}
schemas['ProfileUpdate'].pop('required')

schemas['SceneConfig'] = obj({'maxBytes': integer(format='int64', minimum=1),
                              'sceneMaxFiles': integer(minimum=1), 'sceneMaxBytes': integer(format='int64', minimum=1)})
schemas['SceneFileInput'] = obj({'relativePath': string(minLength=1, maxLength=1024),
                                 'bytes': integer(format='int64', minimum=1), 'sha256': sha})
schemas['SceneCreate'] = obj({'requestKey': uuid, 'name': string(minLength=1, maxLength=200),
                              'description': string(maxLength=2000),
                              'files': array(ref('SceneFileInput'), minItems=1)},
                             ['requestKey', 'name', 'files'])
schemas['SceneUpdate'] = obj({'name': string(minLength=1, maxLength=200), 'description': string(maxLength=2000),
                              'expectedVersion': integer(minimum=0)})
schemas['SceneFile'] = obj({
    'fileId': uuid, 'relativePath': string(minLength=1, maxLength=1024), 'bytes': integer(format='int64', minimum=1),
    'sha256': sha, 'status': file_status, 'failureReason': string(nullable=True), 'attempts': integer(minimum=0)})
scene_summary = {
    'id': uuid, 'name': string(minLength=1, maxLength=200), 'description': string(maxLength=2000),
    'enabled': {'type': 'boolean'}, 'lockVersion': integer(minimum=0), 'uploadStatus': upload_status,
    'fileCount': integer(minimum=0), 'availableCount': integer(minimum=0), 'failedCount': integer(minimum=0),
    'totalBytes': int64, 'createdAt': timestamp, 'updatedAt': timestamp}
schemas['SceneSummary'] = obj(scene_summary)
schemas['SceneDetail'] = obj(dict(scene_summary, files=array(ref('SceneFile'))))
schemas['SceneList'] = obj({'items': array(ref('SceneSummary')), 'total': integer(minimum=0)})

schemas['ClientSceneItem'] = obj({'id': uuid, 'name': string(minLength=1)})
schemas['ClientSceneList'] = obj({'items': array(ref('ClientSceneItem')), 'total': integer(minimum=0)})
schemas['ClientFile'] = obj({'fileId': uuid, 'relativePath': string(minLength=1, maxLength=1024),
                             'bytes': integer(format='int64', minimum=1), 'sha256': sha, 'contentType': string(),
                             'downloadPath': string()})
schemas['ClientSceneDetail'] = obj({'sceneId': uuid, 'name': string(minLength=1),
                                    'files': array(ref('ClientFile'), minItems=1),
                                    'fileCount': integer(minimum=1), 'totalBytes': int64})

paths = {}

def add(path, method, operation, summary, request=None, response=None, status='200', public=False, description='',
        query=None, tag='场景'):
    params = [{'name': n, 'in': 'path', 'required': True,
               'schema': integer(format='int64') if n == 'operId' else string() if n in ('code', 'dictType', 'fileName') else uuid}
              for n in re.findall(r'\{([^}]+)\}', path)]
    params.extend(query or [])
    responses = {status: {'description': 'Success'}}
    if response: responses[status]['content'] = {'application/json': {'schema': ref(response)}}
    for code in (('400', '404', '409', '413', '429', '503') if public else
                 ('400', '401', '403', '404', '409', '413', '429', '503')):
        responses[code] = {'description': 'Request failed; 409 covers state conflicts',
                           'content': {'application/json': {'schema': ref('Error')}}}
    op = {'operationId': operation, 'summary': summary, 'description': description or summary,
          'security': [] if public else [{'bearerAuth': []}], 'parameters': params, 'responses': responses,
          'x-implementation': 'implemented', 'tags': [tag]}
    if request:
        op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': ref(request)}}}
    paths.setdefault(path, {})[method] = op
    return op

def query(name, schema, required=True): return {'name': name, 'in': 'query', 'required': required, 'schema': schema}
def header(name, description): return {'name': name, 'in': 'header', 'required': False, 'schema': string(), 'description': description}

paging = [query('limit', integer(minimum=1, maximum=100, default=20), False), query('offset', integer(minimum=0, default=0), False)]
admin_only = '仅 ar_admin 管理员；AR_STORAGE_ENABLED=true 时开放。'
fixed_files = '一个场景只有一份创建后固定的文件清单；上传完成并校验后，启用状态下自动对匿名客户端可见，没有发布操作。'

add('/api/v1/scenes/config', 'get', 'sceneConfig', '查看单文件与单场景上传上限', response='SceneConfig',
    description=admin_only + '返回 AR_STORAGE_MAX_BYTES、AR_STORAGE_SCENE_MAX_FILES、AR_STORAGE_SCENE_MAX_BYTES 的运行值。')
create_scene = add('/api/v1/scenes', 'post', 'createScene', '创建场景与固定文件清单', 'SceneCreate', 'SceneDetail', '201',
    description=admin_only + fixed_files + '一次事务登记名称、说明和全部文件（相对路径、大小、SHA256）；默认启用。'
                '同 requestKey 且名称、说明、文件清单完全相同时重试返回 200 与原场景；不同返回 409；'
                '同 requestKey 对应已删除或删除中的场景返回 410，不复活。大小或数量超配置返回 413，路径不合法返回 400。')
create_scene['responses']['200'] = {'description': '完全相同的重试，返回原场景详情',
                                    'content': {'application/json': {'schema': ref('SceneDetail')}}}
create_scene['responses']['410'] = {'description': '同请求键的场景已删除或正在删除，不复活',
                                    'content': {'application/json': {'schema': ref('Error')}}}
add('/api/v1/scenes', 'get', 'listScenes', '列出场景概要', response='SceneList', query=paging + [query('name', string(maxLength=200), False)],
    description=admin_only + '按创建时间倒序；不含已完全删除的场景，删除中/删除失败的场景仍可见以支持重试。')
add('/api/v1/scenes/{sceneId}', 'get', 'getScene', '查看场景与固定文件清单', response='SceneDetail',
    description=admin_only + '文件不分页一次返回；uploadStatus 为 PENDING/UPLOADING/FAILED/READY/DELETING/DELETE_FAILED。')
add('/api/v1/scenes/{sceneId}', 'put', 'updateScene', '修改场景名称和说明', 'SceneUpdate', 'SceneDetail',
    description=admin_only + '只修改名称和说明，文件清单创建后固定。expectedVersion 为场景 lockVersion，冲突 409；'
                '删除中的场景 409。')
add('/api/v1/scenes/{sceneId}', 'delete', 'deleteScene', '整场景物理删除', status='204',
    query=[query('expectedVersion', integer(minimum=0))],
    description=admin_only + '先持久化删除意图再清理存储文件；上传进行中 409，不改写活动字节流。'
                '存储删除失败 503 并保留意图，可重试；成功后重复 DELETE 返回 204，意图完成后忽略过期 expectedVersion。'
                '不存在且无回执 404。删除的文件行不保留，场景行与最小删除回执保留。')
add('/api/v1/scenes/{sceneId}/enabled', 'put', 'setSceneEnabled', '启用或停用场景', 'EnabledUpdate', 'SceneDetail',
    description=admin_only + 'reason 必填并写入审计。启停只影响新的匿名读取；已有文件流可完成。'
                '上传与恢复从不自动启用场景。expectedVersion 为场景 lockVersion，冲突 409。')
add('/api/v1/audits', 'get', 'listAudits', '只读场景业务审计', response='AuditList', query=paging,
    description=admin_only + '包含 SCENE_CREATE、SCENE_UPDATE、SCENE_SET_ENABLED、SCENE_DELETE_REQUEST、SCENE_DELETE、'
                'SCENE_DELETE_FAILED 与文件上传结果动作；历史 VERSION_* 标签作为不可变历史记录保留。')
add('/api/v1/scenes/{sceneId}/files/{fileId}', 'get', 'getSceneFile', '查看单文件状态', response='SceneFile',
    description=admin_only + '请求结果未确认后用于核对文件状态。')
upload = add('/api/v1/scenes/{sceneId}/files/{fileId}/content', 'put', 'uploadSceneFile', '流式上传并校验文件',
    response='SceneFile',
    description=admin_only + '原始字节流。接收时一次校验实际大小与 SHA256，通过后无覆盖提交并直接 AVAILABLE；'
                '已 AVAILABLE 的文件不覆盖。每次新尝试 attempts 加一。大小或摘要不符 422，存储 IO 失败 503，'
                '均持久化 FAILED 与原因；同文件处理中 409。请求超时只代表结果未确认，先 GET 单文件核对。无分片协议。')
upload['requestBody'] = {'required': True, 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}
upload['responses']['422'] = {'description': '实际大小或 SHA256 与登记不符；失败原因已持久化',
                              'content': {'application/json': {'schema': ref('Error')}}}
download = add('/api/v1/scenes/{sceneId}/files/{fileId}/content', 'get', 'downloadSceneFile', '管理员读取单个文件',
    query=[header('Range', '单个 bytes Range；无效或多段 Range 忽略并返回完整文件'), header('If-Range', '强 ETag，不匹配返回完整文件')],
    description=admin_only + '文件必须 AVAILABLE 且场景无删除意图；允许尚未全部上传的场景读取已完成文件，'
                '场景停用不影响管理员读取。强 ETag 为登记的 SHA256，支持 Range、If-Range；不重算其他文件。'
                '管理员下载带 attachment 文件名。')
head = copy.deepcopy(download)
head.update(operationId='headSceneFile', summary='查询管理员单文件下载头')
binary = {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}
for operation in (download, head):
    operation['responses']['200'] = {'description': '完整文件', 'content': binary}
    operation['responses']['206'] = {'description': '单段 Range', 'content': binary}
    operation['responses']['416'] = {'description': 'Range 越界；Content-Range 为 bytes */size'}
paths['/api/v1/scenes/{sceneId}/files/{fileId}/content']['head'] = head

client_note = ('匿名只读，无需 Authorization；仅 AR_STORAGE_ENABLED=true 时开放。场景须启用、未删除、未在删除中，'
               '且固定文件清单非空并全部 AVAILABLE，否则 404。')
add('/api/v1/client/scenes', 'get', 'listClientScenes', '匿名列出可读场景', response='ClientSceneList', public=True,
    query=paging + [query('name', string(maxLength=200), False)], tag='客户端',
    description=client_note + '每项只含场景 id 与名称；只读数据库，不打开任何文件。空目录返回 200 与空数组。')
add('/api/v1/client/scenes/{sceneId}', 'get', 'getClientScene', '匿名读取场景固定文件清单', response='ClientSceneDetail',
    public=True, tag='客户端',
    description=client_note + 'files 是场景的固定文件集合，按 relativePath 排序；客户端按相对路径自行组织资源。'
                'downloadPath 是相对同源根的直接下载地址。不返回 storageKey 或磁盘路径，不读取文件内容。')
client_content = '/api/v1/client/scenes/{sceneId}/files/{fileId}/content/{fileName}'
client_download = add(client_content, 'get', 'downloadClientFile', '匿名读取场景文件', public=True, tag='客户端',
    query=[header('Range', '单个 bytes Range，含 bytes=a-b、bytes=a- 与后缀 bytes=-n；无效或多段 Range 忽略并返回完整文件'),
           header('If-Range', '强 ETag，不匹配返回完整文件')],
    description=client_note + 'fileName 为文件实际 basename 的 URI 编码，仅用于保留扩展名并与记录比对，不参与磁盘路径；不符 404。'
                '文件记录存在但存储缺失或长度不符返回 409（存储问题，重试可能恢复），不是业务版本变化。'
                '下载前不重算摘要，强 ETag 为登记的 SHA256；响应不带 attachment 文件名，Cache-Control 为 no-store, no-transform。'
                'Content-Type 只按扩展名：json 为 application/json，jpg/png/webp、wav、webm 对应 MIME，模型与未知类型为 application/octet-stream。')
client_head = copy.deepcopy(client_download)
client_head.update(operationId='headClientFile', summary='匿名查询场景文件下载头')
client_binary = {mime: {'schema': {'type': 'string', 'format': 'binary'}}
                 for mime in ('application/octet-stream', 'application/json', 'image/jpeg', 'image/png', 'image/webp',
                              'audio/wav', 'video/webm')}
for operation in (client_download, client_head):
    operation['responses']['200'] = {'description': '完整文件；HEAD 无正文但带完整 Content-Length', 'content': client_binary}
    operation['responses']['206'] = {'description': '单段 Range', 'content': client_binary}
    operation['responses']['416'] = {'description': 'Range 合法但越界；Content-Range 为 bytes */size'}
paths[client_content]['head'] = client_head

for path, method, operation, summary, request in [
    ('/login', 'post', 'login', '登录；成功返回 token', 'Login'),
    ('/logout', 'post', 'logout', '退出登录', None),
    ('/getInfo', 'get', 'getInfo', '当前用户及权限', None),
    ('/getRouters', 'get', 'getRouters', '当前用户菜单', None),
    ('/captchaImage', 'get', 'captchaConfig', '验证码开关与挑战；本地 Demo 关闭验证码', None),
    ('/system/user/profile', 'get', 'profile', '本人资料', None),
    ('/system/user/profile', 'put', 'updateProfile', '修改本人资料', 'ProfileUpdate'),
    ('/system/user/list', 'get', 'listUsers', '账号分页列表', None),
    ('/system/user', 'post', 'createUser', '创建固定角色管理员', 'AccountCreate'),
    ('/system/user/changeStatus', 'put', 'changeUserStatus', '修改账号状态', 'AccountStatus'),
    ('/system/user/resetPwd', 'put', 'resetPassword', '重置密码并撤销旧凭证', 'AccountPassword'),
    ('/system/user/profile/updatePwd', 'put', 'changeOwnPassword', '修改本人密码并撤销旧凭证', 'OwnPassword'),
    ('/monitor/logininfor/list', 'get', 'loginLogs', '登录日志分页', None),
    ('/monitor/operlog/list', 'get', 'operationLogs', '操作日志分页', None),
    ('/monitor/operlog/{operId}', 'get', 'operationLogDetail', '操作日志详情', None),
    ('/system/dict/data/type/{dictType}', 'get', 'dictionaryValues', '界面状态字典', None),
]:
    op = add(path, method, operation, summary, request, 'FrameworkResponse', public=operation in ('login', 'captchaConfig'),
             tag='若依框架')
    op['description'] += '。沿用若依 code/msg 响应；业务错误可能使用 HTTP 200。'
    for response in op['responses'].values():
        response['content'] = {'application/json': {'schema': ref('FrameworkResponse')}}
    if method == 'get' and path.endswith('/list'):
        op['parameters'] += [query('pageNum', integer(minimum=1, default=1), False), query('pageSize', integer(minimum=1, default=20), False)]

spec = {'openapi': '3.0.3', 'info': {'title': '4DGS Scene Resource API', 'version': '0.6.0',
         'description': '4DGS 场景资源分发：管理员按名称、说明和固定文件清单创建场景，逐文件上传校验，启用后匿名客户端直接读取目录、'
                        '固定文件清单与带 Range 的文件流；支持名称/说明编辑、启停和整场景物理删除，没有版本或发布指针。'
                        '保留若依登录与账号接口。匿名读取位于 /api/v1/client/，经同源网关直接访问，无需 /prod-api。'},
        'servers': [{'url': '/', 'description': '同源网关；管理接口经 /prod-api 前缀代理到后端'}], 'paths': paths,
        'components': {'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}}, 'schemas': schemas}}

if __name__ == '__main__':
    (ROOT/'contracts/openapi.yaml').write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print('Generated', sum(len(v) for v in paths.values()), 'operations')
