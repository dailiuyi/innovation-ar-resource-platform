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


version_status = enum('PENDING', 'UPLOADING', 'AVAILABLE', 'FAILED')
upload_status = enum('DELETING', 'DELETE_FAILED', 'UPLOADING', 'FAILED', 'READY', 'PENDING')
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
    'SceneCreate': obj({'name': string(minLength=1, maxLength=200)}),
    'EnabledUpdate': obj({'enabled': {'type': 'boolean'}, 'expectedVersion': integer(minimum=0),
                          'reason': string(minLength=1)}),
    'AuditList': obj({'items': array({'type': 'object', 'additionalProperties': True}), 'total': integer(minimum=0)}),
}
schemas['ProfileUpdate'].pop('required')
schemas['SceneUpdate'] = obj(dict(schemas['SceneCreate']['properties'], expectedVersion=integer(minimum=0)),
                             ['name', 'expectedVersion'])
schemas['SceneView'] = obj(dict(schemas['SceneCreate']['properties'], id=uuid, enabled={'type': 'boolean'},
                                lockVersion=integer(minimum=0), createdAt=timestamp, updatedAt=timestamp),
                           ['id', 'name', 'enabled', 'lockVersion', 'createdAt', 'updatedAt'])
schemas['SceneList'] = obj({'items': array(ref('SceneView')), 'total': integer(minimum=0)})

schemas['VersionConfig'] = obj({'maxBytes': integer(format='int64', minimum=1),
                                'versionMaxFiles': integer(minimum=1), 'versionMaxBytes': integer(format='int64', minimum=1)})
schemas['VersionFileRegistration'] = obj({'relativePath': string(minLength=1, maxLength=1024),
                                          'bytes': integer(format='int64', minimum=1), 'sha256': sha})
schemas['VersionCreate'] = obj({'requestKey': uuid, 'description': string(maxLength=2000),
                                'files': array(ref('VersionFileRegistration'), minItems=1, maxItems=1000)})
schemas['VersionEdit'] = obj({'description': string(maxLength=2000), 'expectedVersion': integer(minimum=0)})
schemas['VersionPublish'] = obj({'expectedSceneVersion': integer(minimum=0)})
version_summary = {
    'id': uuid, 'sceneId': uuid, 'versionNo': integer(minimum=1), 'description': string(maxLength=2000),
    'lockVersion': integer(minimum=0), 'published': {'type': 'boolean'}, 'uploadStatus': upload_status,
    'fileCount': integer(minimum=0), 'availableCount': integer(minimum=0), 'failedCount': integer(minimum=0),
    'totalBytes': int64, 'creatorId': integer(format='int64'), 'creatorName': string(),
    'createdAt': timestamp, 'updatedAt': timestamp}
schemas['VersionSummary'] = obj(version_summary)
schemas['PublishedVersion'] = obj({'id': uuid, 'versionNo': integer(minimum=1), 'description': string(maxLength=2000),
                                   'publishedAt': timestamp, 'publishedByName': string()})
schemas['VersionList'] = obj({'items': array(ref('VersionSummary')), 'total': integer(minimum=0),
                              'sceneLockVersion': integer(minimum=0), 'published': ref('PublishedVersion')},
                             ['items', 'total', 'sceneLockVersion'])
schemas['VersionFile'] = obj({
    'fileId': uuid, 'relativePath': string(minLength=1, maxLength=1024), 'bytes': integer(format='int64', minimum=1),
    'sha256': sha, 'status': version_status, 'failureReason': string(nullable=True), 'attempts': integer(minimum=0)})
schemas['VersionDetail'] = obj(dict(version_summary, files=array(ref('VersionFile'))))

schemas['ClientSceneItem'] = obj({'id': uuid, 'name': string(minLength=1), 'versionId': uuid, 'versionNo': integer(minimum=1)})
schemas['ClientSceneList'] = obj({'items': array(ref('ClientSceneItem')), 'total': integer(minimum=0)})
schemas['ClientFile'] = obj({'fileId': uuid, 'relativePath': string(minLength=1, maxLength=1024),
                             'bytes': integer(format='int64', minimum=1), 'sha256': sha, 'contentType': string(),
                             'downloadPath': string()})
schemas['ClientSceneDetail'] = obj({'sceneId': uuid, 'name': string(minLength=1), 'versionId': uuid,
                                    'versionNo': integer(minimum=1), 'files': array(ref('ClientFile'), minItems=1),
                                    'fileCount': integer(minimum=1), 'totalBytes': int64})

paths = {}

def add(path, method, operation, summary, request=None, response=None, status='200', public=False, description='',
        query=None, tag='场景版本'):
    params = [{'name': n, 'in': 'path', 'required': True,
               'schema': integer(format='int64') if n == 'operId' else string() if n in ('code', 'dictType', 'fileName') else uuid}
              for n in re.findall(r'\{([^}]+)\}', path)]
    params.extend(query or [])
    responses = {status: {'description': 'Success'}}
    if response: responses[status]['content'] = {'application/json': {'schema': ref(response)}}
    for code in ('400', '401', '403', '404', '409', '413', '429', '503'):
        responses[code] = {'description': 'Request failed; 409 covers state/version conflict',
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

add('/api/v1/scenes', 'post', 'createScene', '创建场景', 'SceneCreate', 'SceneView', '201', tag='场景')
add('/api/v1/scenes', 'get', 'listScenes', '列出场景', response='SceneList', tag='场景',
                  query=paging + [query('name', string(maxLength=200), False)])
add('/api/v1/scenes/{sceneId}', 'get', 'getScene', '查看场景', response='SceneView', tag='场景')
add('/api/v1/scenes/{sceneId}', 'put', 'updateScene', '修改场景名称', 'SceneUpdate', 'SceneView', tag='场景')
add('/api/v1/scenes/{sceneId}', 'delete', 'deleteScene', '逻辑删除场景', status='204', tag='场景',
    query=[query('expectedVersion', integer(minimum=0))],
    description='逻辑删除，不递归删除成品版本和文件内容；匿名目录不再返回该场景。')
add('/api/v1/scenes/{sceneId}/enabled', 'put', 'setSceneEnabled', '启用或禁用场景', 'EnabledUpdate', 'SceneView', tag='场景')
add('/api/v1/audits', 'get', 'listAudits', '只读场景业务审计', response='AuditList', query=paging, tag='场景',
    description='动作包括 SCENE_* 与上传结果动作，以及 VERSION_CREATE、VERSION_EDIT、VERSION_PUBLISH、'
                'VERSION_DELETE_REQUEST、VERSION_DELETE、VERSION_DELETE_FAILED。')

add('/api/v1/scene-versions/config', 'get', 'versionConfig', '查看单文件与单版本上传上限', response='VersionConfig',
    description=admin_only + '返回 AR_STORAGE_MAX_BYTES、AR_STORAGE_VERSION_MAX_FILES、AR_STORAGE_VERSION_MAX_BYTES 的运行值。')
add('/api/v1/scenes/{sceneId}/versions', 'get', 'listSceneVersions', '分页列出场景的成品版本', response='VersionList', query=paging,
    description=admin_only + '含 sceneLockVersion；当前发布版本以 published 对象返回，未发布时省略该字段。'
                '每项 uploadStatus 由文件状态读时推导：DELETING/DELETE_FAILED/UPLOADING/FAILED/READY/PENDING。')
create_version = add('/api/v1/scenes/{sceneId}/versions', 'post', 'createSceneVersion', '导入资源目录，创建成品版本',
    'VersionCreate', 'VersionDetail', '201',
    description=admin_only + '一次登记所选目录下的全部文件（相对路径、大小、SHA256），创建后清单不可变，只有说明可编辑。'
                '平台不解析档位、分段或时间，这些由客户端按相对路径约定处理。'
                '同 requestKey 且 description、文件清单完全相同返回 200 与原版本，不同返回 409，'
                '已整版删除的版本迟到重试返回 410。大小或数量超配置返回 413，路径不合法返回 400 并指出路径。')
create_version['responses']['200'] = {'description': '完全相同的重试，返回原版本',
                                      'content': {'application/json': {'schema': ref('VersionDetail')}}}
create_version['responses']['410'] = {'description': '同请求键的版本已整版删除，不复活',
                                      'content': {'application/json': {'schema': ref('Error')}}}
add('/api/v1/scene-versions/{versionId}', 'get', 'getSceneVersion', '查看版本和完整文件清单', response='VersionDetail',
    description=admin_only + '文件不分页，1000 个文件以内一次返回；不读取文件内容、不计算摘要。')
add('/api/v1/scene-versions/{versionId}', 'put', 'editSceneVersion', '编辑版本说明', 'VersionEdit', 'VersionDetail',
    description=admin_only + '只编辑说明；文件清单创建后固定。expectedVersion 为版本 lockVersion，冲突 409。')
add('/api/v1/scene-versions/{versionId}', 'delete', 'deleteSceneVersion', '整版物理删除', status='204',
    description=admin_only + '当前发布版本 409，文件处理中 409。先持久化删除意图，再逐文件删除存储内容；'
                '存储失败 503 并保留版本，可再次 DELETE 重试；成功后重复 DELETE 为 204。不存在且无回执 404。')
add('/api/v1/scene-versions/{versionId}/publish', 'post', 'publishSceneVersion', '发布为场景的当前版本',
    'VersionPublish', 'VersionDetail',
    description=admin_only + '全部文件 AVAILABLE 且无删除意图才可发布；未完成 400，处理中 409。已是当前版本直接 200 且无任何写入；'
                '实际切换时 expectedSceneVersion 为场景 lockVersion，冲突 409。发布不解析模型、不重算摘要。')
add('/api/v1/scene-versions/{versionId}/files/{fileId}', 'get', 'getSceneVersionFile', '查看单文件状态', response='VersionFile',
    description=admin_only + '请求结果未确认后用于核对文件状态。')
upload = add('/api/v1/scene-versions/{versionId}/files/{fileId}/content', 'put', 'uploadSceneVersionFile', '流式上传并校验文件',
    response='VersionFile',
    description=admin_only + '原始字节流。接收时一次校验实际大小与 SHA256，通过后无覆盖提交并直接 AVAILABLE；已 AVAILABLE 的文件不覆盖。'
                '每次新尝试 attempts 加一。大小或摘要不符 422，存储 IO 失败 503，均持久化 FAILED 与原因；同文件处理中 409。'
                '请求超时只代表结果未确认，先 GET 单文件核对。无分片协议。')
upload['requestBody'] = {'required': True, 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}
upload['responses']['422'] = {'description': '实际大小或 SHA256 与登记不符；失败原因已持久化',
                              'content': {'application/json': {'schema': ref('Error')}}}
download = add('/api/v1/scene-versions/{versionId}/files/{fileId}/content', 'get', 'downloadSceneVersionFile', '管理员读取单个文件',
    query=[header('Range', '单个 bytes Range；无效或多段 Range 忽略并返回完整文件'), header('If-Range', '强 ETag，不匹配返回完整文件')],
    description=admin_only + '文件必须 AVAILABLE 且版本无删除意图；允许尚未全部上传的版本读取已完成文件。'
                '强 ETag 为登记的 SHA256，支持 Range、If-Range；不重算其他文件。管理员下载带 attachment 文件名。')
head = copy.deepcopy(download)
head.update(operationId='headSceneVersionFile', summary='查询管理员单文件下载头')
binary = {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}
for operation in (download, head):
    operation['responses']['200'] = {'description': '完整文件', 'content': binary}
    operation['responses']['206'] = {'description': '单段 Range', 'content': binary}
    operation['responses']['416'] = {'description': 'Range 越界；Content-Range 为 bytes */size'}
paths['/api/v1/scene-versions/{versionId}/files/{fileId}/content']['head'] = head

client_note = '匿名只读，无需 Authorization；仅 AR_STORAGE_ENABLED=true 时开放。场景须启用、未删除且有完整的当前发布版本，否则 404。'
add('/api/v1/client/scenes', 'get', 'listClientScenes', '匿名列出已发布场景', response='ClientSceneList', public=True,
    query=paging + [query('name', string(maxLength=200), False)], tag='客户端',
    description=client_note + '每项只含场景与当前发布版本标识；只读数据库，不打开任何文件。空目录返回 200 与空数组。')
add('/api/v1/client/scenes/{sceneId}', 'get', 'getClientScene', '匿名读取已发布场景的完整文件清单', response='ClientSceneDetail',
    public=True, tag='客户端',
    description=client_note + 'files 是该版本的完整文件集合，按 relativePath 排序；档位、分段与公共文件的选择由客户端按相对路径自行决定。'
                '不返回 storageKey 或磁盘路径。不读取文件内容。')
client_content = '/api/v1/client/scenes/{sceneId}/versions/{versionId}/files/{fileId}/content/{fileName}'
client_download = add(client_content, 'get', 'downloadClientFile', '匿名读取已发布版本的单个文件', public=True, tag='客户端',
    query=[header('Range', '单个 bytes Range，含 bytes=a-b、bytes=a- 与后缀 bytes=-n；无效或多段 Range 忽略并返回完整文件'),
           header('If-Range', '强 ETag，不匹配返回完整文件')],
    description=client_note + 'fileName 为文件实际 basename 的 URI 编码，仅用于保留扩展名并与记录比对，不参与磁盘路径；不符 404。'
                '版本须仍是当前发布版本，否则 409（已开始的字节流可完成，下一请求 409）；文件记录存在但存储缺失或长度不符 409。'
                '下载前不重算摘要，强 ETag 为登记的 SHA256；响应不带 attachment 文件名，Cache-Control 为 no-store, no-transform。'
                'Content-Type 只按扩展名：json 为 application/json，jpg/png/webp、wav、webm 对应 MIME，模型与未知类型为 application/octet-stream。')
client_head = copy.deepcopy(client_download)
client_head.update(operationId='headClientFile', summary='匿名查询单个文件下载头')
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
    op = add(path, method, operation, summary, request, 'FrameworkResponse', public=operation in ('login', 'captchaConfig'), tag='若依框架')
    op['description'] += '。沿用若依 code/msg 响应；业务错误可能使用 HTTP 200。'
    for response in op['responses'].values():
        response['content'] = {'application/json': {'schema': ref('FrameworkResponse')}}
    if method == 'get' and path.endswith('/list'):
        op['parameters'] += [query('pageNum', integer(minimum=1, default=1), False), query('pageSize', integer(minimum=1, default=20), False)]

spec = {'openapi': '3.0.3', 'info': {'title': '4DGS Scene Resource API', 'version': '0.5.0',
         'description': '4DGS 场景成品：管理员侧的场景、由目录文件清单构成的内容版本、按文件上传与恢复、单一发布指针、整版删除，'
                        '以及保留的若依登录与账号接口；匿名客户端只读目录、文件清单与带 Range 的文件流（/api/v1/client/，经同源网关直接访问，无需 /prod-api）。'},
        'servers': [{'url': '/', 'description': '同源网关；管理接口经 /prod-api 前缀代理到后端'}], 'paths': paths,
        'components': {'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}}, 'schemas': schemas}}

if __name__ == '__main__':
    (ROOT/'contracts/openapi.yaml').write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print('Generated', sum(len(v) for v in paths.values()), 'operations')
