from app import apfell, db_objects
from sanic_jwt.decorators import inject_user, scoped
import app.database_models.model as db_model
from sanic.response import json
from sanic.exceptions import abort
import json as js
import base64
from sanic.log import logger


# -------  BROWSER SCRIPT FUNCTION -----------------
# scripts without a command tied to them are available as support functions
@apfell.route(apfell.config['API_BASE'] + "/browser_scripts", methods=['GET'])
@inject_user()
@scoped(['auth:user', 'auth:apitoken_c2', 'auth:apitoken_user'], False)  # user or user-level api token are ok
async def get_browserscripts(request, user):
    if user['auth'] not in ['access_token', 'apitoken']:
        abort(status_code=403, message="Cannot access via Cookies. Use CLI or access via JS in browser")
    try:
        query = await db_model.operator_query()
        operator = await db_objects.get(query, username=user['username'])
        query = await db_model.operation_query()
        operation = await db_objects.get(query, name=user['current_operation'])
        query = await db_model.browserscript_query()
        operator_scripts = await db_objects.execute(
            query.where((db_model.BrowserScript.operator == operator) & (db_model.BrowserScript.command != None)))
        support_scripts = await db_objects.execute(
            query.where((db_model.BrowserScript.operator == operator) & (db_model.BrowserScript.command == None)))
        query = await db_model.browserscriptoperation_query()
        operation_scripts = await db_objects.execute(
            query.where(db_model.BrowserScriptOperation.operation == operation))
        return json({"status": "success",
                     "operator_scripts": [o.to_json() for o in operator_scripts],
                     "operation_scripts": [o.to_json() for o in operation_scripts],
                     "support_scripts": [o.to_json() for o in support_scripts]})
    except Exception as e:
        print(str(e))
        return json({"status": "error", 'error': 'failed to find user or scripts'})


@apfell.route(apfell.config['API_BASE'] + "/browser_scripts", methods=['POST'])
@inject_user()
@scoped(['auth:user', 'auth:apitoken_user'], False)  # user or user-level api token are ok
async def create_browserscript(request, user):
    if user['auth'] not in ['access_token', 'apitoken']:
        abort(status_code=403, message="Cannot access via Cookies. Use CLI or access via JS in browser")
    try:
        data = request.json
    except Exception as e:
        return json({'status': 'error', 'error': 'failed to parse json'})
    pieces = {}
    if 'script' not in data:
        return json({'status': 'error', 'error': 'must supply "script" '})
    if 'command' in data:
        try:
            query = await db_model.command_query()
            command = await db_objects.get(query, id=data['command'])
            pieces['command'] = command
        except Exception as e:
            return json({"status": 'error', 'error': 'failed to find command: ' + str(e)})
    query = await db_model.operator_query()
    operator = await db_objects.get(query, username=user['username'])
    pieces['operator'] = operator
    if 'name' in data:
        pieces['name'] = data['name']
        pieces['command'] = None
    pieces['script'] = data['script']
    try:
        browserscript = await db_objects.get(db_model.BrowserScript, command=pieces['command'], name=pieces['name'], operator=operator)
        return json({'status': 'error', 'error': 'Script with that name or for that command already exists for this user'})
    except Exception as e:
        # if we get here then the script doesn't exist, so we can create it
        browserscript = await db_objects.create(db_model.BrowserScript, **pieces)
        return json({'status': 'success', **browserscript.to_json()})



@apfell.route(apfell.config['API_BASE'] + "/browser_scripts/<bid:int>", methods=['PUT'])
@inject_user()
@scoped(['auth:user', 'auth:apitoken_user'], False)  # user or user-level api token are ok
async def modify_browserscript(request, user, bid):
    if user['auth'] not in ['access_token', 'apitoken']:
        abort(status_code=403, message="Cannot access via Cookies. Use CLI or access via JS in browser")
    try:
        data = request.json
    except Exception as e:
        return json({'status': 'error', 'error': 'failed to parse json'})
    try:
        updated_script = False
        query = await db_model.operator_query()
        operator = await db_objects.get(query, username=user['username'])
        query = await db_model.browserscript_query()
        try:
            browserscript = await db_objects.get(query, id=bid)  # you can only modify your own scripts
        except Exception as e:
            return json({'status': 'error', 'error': 'failed to find script'})
        if browserscript.operator.username != operator.username:
            return json({'status': 'error', 'error': 'you can only modify your scripts'})
        if 'command' in data:
            if data['command'] == "" and "name" in data and data['name'] != "":
                browserscript.command = None
                browserscript.name = data['name']
            elif data['command'] != "":
                query = await db_model.command_query()
                command = await db_objects.get(query, id=data['command'])
                browserscript.command = command
            else:
                return json({'status': 'error',  'error': 'if setting command to empty, must set name to something'})
            updated_script = True
        elif 'name' in data and data['name'] != "":
            browserscript.name = data['name']
            browserscript.command = None
            updated_script = True
        if 'script' in data:
            browserscript.script = data['script']
            updated_script = True
        if 'active' in data:
            browserscript.active = True if data['active'] is True else False
            updated_script = True
            if not browserscript.active:
                # make sure the script is not part of any operation
                query = await db_model.browserscriptoperation_query()
                script = await db_objects.execute(query)
                for s in script:
                    if s.browserscript == browserscript:
                        await db_objects.delete(s)
        if updated_script:
            await db_objects.update(browserscript)
        if 'operation' in data:
            if data['operation'] != user['current_operation'] and data['operation'] != "":
                return json({'status': 'error', 'error': 'cannot set operation to something other than current operation'})
            if data['operation'] in user['admin_operations'] or user['admin']:
                # we are an admin overall or admin of this operation and we're trying to apply to the current operation
                query = await db_model.operation_query()
                operation = await db_objects.get(query, name=user['current_operation'])
                query = await db_model.browserscriptoperation_query()
                if data['operation'] != "":
                    if not browserscript.active:
                        return json({'status': 'error', 'error': 'cannot assign a script to an operation that is not active'})
                    # make sure it's ok to apply first
                    can_add = True
                    script = await db_objects.execute(query.where(db_model.BrowserScriptOperation.operation == operation) )
                    for s in script:
                        if s.browserscript == browserscript:
                            can_add = False  # it's already added to the operation
                        elif browserscript.command is None and s.browserscript.name == browserscript.name:
                            can_add = False  # already have a support script by the same name
                        elif s.browserscript.command == browserscript.command:
                            can_add = False  # there's already a script for that command
                    if can_add:
                        mapping = await db_objects.create(db_model.BrowserScriptOperation, operation=operation, browserscript=browserscript)
                else:
                    script = await db_objects.execute(query.where(db_model.BrowserScriptOperation.operation == operation))
                    for s in script:
                        if s.browserscript == browserscript:
                            await db_objects.delete(s)
            else:
                return json(
                    {'status': 'error', 'error': 'you must be the operation admin to apply scripts to the operation'})
        return json({'status': 'success', **browserscript.to_json()})
    except Exception as e:
        logger.exception("error trying to update browserscript")
        return json({"status": "error", 'error': 'failed to find or set information: ' + str(e)})


async def remove_admin_browserscripts(operator, operation):
    query = await db_model.browserscriptoperation_query()
    scripts = await db_objects.execute(query.where( (db_model.BrowserScriptOperation.operation == operation) & (db_model.BrowserScript.operator == operator)))
    for s in scripts:
        await db_objects.delete(s)


@apfell.route(apfell.config['API_BASE'] + "/browser_scripts/<bid:int>", methods=['DELETE'])
@inject_user()
@scoped(['auth:user', 'auth:apitoken_user'], False)  # user or user-level api token are ok
async def remove_browserscript(request, user, bid):
    if user['auth'] not in ['access_token', 'apitoken']:
        abort(status_code=403, message="Cannot access via Cookies. Use CLI or access via JS in browser")
    try:
        query = await db_model.operator_query()
        operator = await db_objects.get(query, username=user['username'])
        query = await db_model.browserscript_query()
        browserscript = await db_objects.get(query, id=bid, operator=operator)
        query = await  db_model.browserscriptoperation_query()
        browserscriptoperations = await db_objects.execute(query.where(db_model.BrowserScriptOperation.browserscript == browserscript))
    except Exception as e:
        print(str(e))
        return json({"status": "error", 'error': 'failed to find information: ' + str(e)})
    try:
        browserscript_json = browserscript.to_json()
        for s in browserscriptoperations:
            await db_objects.delete(s)
        await db_objects.delete(browserscript)
        return json({'status': 'success', **browserscript_json})
    except Exception as e:
        print(str(e))
        return json({'status': 'error', 'error': 'failed to remove all browserscript instances: ' + str(e)})


@apfell.route(apfell.config['API_BASE'] + "/browser_scripts/import", methods=['POST'])
@inject_user()
@scoped(['auth:user', 'auth:apitoken_user'], False)  # user or user-level api token are ok
async def import_browserscript(request, user):
    if user['auth'] not in ['access_token', 'apitoken']:
        abort(status_code=403, message="Cannot access via Cookies. Use CLI or access via JS in browser")
    # get json data
    try:
        if request.files:
            code = js.loads(request.files['upload_file'][0].body)
        else:
            input_data = request.json
            if "code" in input_data:
                code = js.loads(base64.b64decode(input_data["code"]))
            else:
                return json({'status': 'error', 'error': 'code must be supplied in base64 or via a form'})
    except Exception as e:
        return json({'status': 'error', 'error': 'failed to parse json'})
    failed_imports = []
    for data in code:
        pieces = {}
        # script is base64 encoded
        if 'script' not in data:
            data['error'] = "script must be supplied in base64 format"
            failed_imports.append(data)
            continue
        if 'command' in data and 'payload_type' in data:
            try:
                query = await db_model.payloadtype_query()
                payload_type = await db_objects.get(query, ptype=data['payload_type'])
                query = await db_model.command_query()
                command = await db_objects.get(query, cmd=data['command'], payload_type=payload_type)
                pieces['command'] = command
            except Exception as e:
                data['error'] = str(e)
                failed_imports.append(data)
                continue
        query = await db_model.operator_query()
        operator = await db_objects.get(query, username=user['username'])
        pieces['operator'] = operator
        if 'name' in data:
            try:
                query = await db_model.browserscript_query()
                script = await db_objects.get(query, name=data['name'])
                data['error'] = "script already exists with that name"
                failed_imports.append(data)
                continue
            except Exception as e:
                # we don't have it in the database yet, so we can make it
                pieces['name'] = data['name']
        pieces['script'] = data['script']
        try:
            browserscript = await db_objects.create(db_model.BrowserScript, **pieces)
        except Exception as e:
            data['error'] = "failed to add script to database: " + str(e)
            failed_imports.append(data)
            continue
    if len(failed_imports) == 0:
        return json({'status': 'success'})
    else:
        return json({'status': 'error', 'error': 'Some of the scripts were not successfully imported.', 'scripts': js.dumps(failed_imports, indent=2)})


@apfell.route(apfell.config['API_BASE'] + "/browser_scripts/export", methods=['GET'])
@inject_user()
@scoped(['auth:user', 'auth:apitoken_user'], False)  # user or user-level api token are ok
async def export_browserscript(request, user):
    if user['auth'] not in ['access_token', 'apitoken']:
        abort(status_code=403, message="Cannot access via Cookies. Use CLI or access via JS in browser")
    scripts = []
    try:
        query = await db_model.operator_query()
        operator = await db_objects.get(query, username=user['username'])
        query = await db_model.browserscript_query()
        operator_scripts = await db_objects.execute(query.where( (db_model.BrowserScript.operator == operator) &
                                                                 (db_model.BrowserScript.command != None)))
        support_scripts = await db_objects.execute(query.where( (db_model.BrowserScript.operator == operator) &
                                                                 (db_model.BrowserScript.command == None)))
        for s in operator_scripts:
            scripts.append({"operator": s.operator.username,
                            "script": s.script,
                            "command": s.command.cmd,
                            "payload_type": s.command.payload_type.ptype})
        for s in support_scripts:
            scripts.append({"operator": s.operator.username,
                            "script": s.script,
                            "name": s.name})
        return json({'status': 'success', 'scripts': scripts})
    except Exception as e:
        return json({'status': 'error','error': str(e)})


@apfell.route(apfell.config['API_BASE'] + "/browser_scripts/export/current_operation", methods=['GET'])
@inject_user()
@scoped(['auth:user', 'auth:apitoken_user'], False)  # user or user-level api token are ok
async def export_operation_browserscript(request, user):
    if user['auth'] not in ['access_token', 'apitoken']:
        abort(status_code=403, message="Cannot access via Cookies. Use CLI or access via JS in browser")
    scripts = []
    try:
        query = await db_model.operation_query()
        operation = await db_objects.get(query, name=user['current_operation'])
        query = await db_model.browserscriptoperation_query()
        operator_scripts = await db_objects.execute(query.where(db_model.BrowserScriptOperation.operation == operation))
        for s in operator_scripts:
            if s.browserscript.command is None:
                scripts.append({"operator": s.browserscript.operator.username,
                                "script": s.browserscript.script,
                                "name": s.browserscript.name})
            else:
                scripts.append({"operator": s.browserscript.operator.username,
                                "script": s.browserscript.script,
                                "command": s.browserscript.command.cmd,
                                "payload_type": s.browserscript.command.payload_type.ptype})
        return json({'status': 'success', 'scripts': scripts})
    except Exception as e:
        return json({'status': 'error','error': str(e)})