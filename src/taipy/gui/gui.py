# Copyright 2023 Avaiga Private Limited
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
# an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

from __future__ import annotations

import contextlib
import inspect
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import typing as t
import warnings
from importlib import util
from types import FrameType
from urllib.parse import unquote, urlencode, urlparse

import __main__
import markdown as md_lib
import tzlocal
from flask import Blueprint, Flask
from flask import __version__ as flask_version  # type: ignore
from flask import g, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from taipy.logger._taipy_logger import _TaipyLogger

if util.find_spec("pyngrok"):
    from pyngrok import ngrok

from ._default_config import _default_stylekit, default_config
from ._page import _Page
from ._warnings import _warn
from .config import Config, ConfigParameter, ServerConfig, Stylekit, _Config
from .data.content_accessor import _ContentAccessor
from .data.data_accessor import _DataAccessor, _DataAccessors
from .data.data_format import _DataFormat
from .data.data_scope import _DataScopes
from .extension.library import Element, ElementLibrary
from .page import Page
from .partial import Partial
from .renderers import _EmptyPage
from .renderers._markdown import _TaipyMarkdownExtension
from .renderers.factory import _Factory
from .renderers.json import _TaipyJsonEncoder
from .renderers.utils import _get_columns_dict
from .server import _Server
from .state import State
from .types import _WsType
from .utils import (
    _delscopeattr,
    _filter_locals,
    _get_broadcast_var_name,
    _get_client_var_name,
    _get_css_var_value,
    _get_module_name_from_frame,
    _get_non_existent_file_path,
    _getscopeattr,
    _getscopeattr_drill,
    _hasscopeattr,
    _is_in_notebook,
    _LocalsContext,
    _MapDict,
    _setscopeattr,
    _setscopeattr_drill,
    _TaipyBase,
    _TaipyContent,
    _TaipyContentImage,
    _TaipyData,
    _TaipyLov,
    _TaipyLovValue,
    _to_camel_case,
    _variable_decode,
    is_debugging,
)
from .utils._adapter import _Adapter
from .utils._bindings import _Bindings
from .utils._evaluator import _Evaluator
from .utils._variable_directory import _MODULE_ID, _VariableDirectory
from .utils.chart_config_builder import _build_chart_config
from .utils.table_col_builder import _enhance_columns


class _DoNotUpdate:
    def __repr__(self):
        return "Taipy: Do not update"


class Gui:
    """Entry point for the Graphical User Interface generation.

    Attributes:

        on_action (Callable): The function that is called when a control
            triggers an action, as the result of an interaction with the end-user.<br/>
            It defaults to the `on_action()` global function defined in the Python
            application. If there is no such function, actions will not trigger anything.<br/>
            The signature of the *on_action* callback function must be:

            - *state*: the `State^` instance of the caller.
            - *id* (optional): a string representing the identifier of the caller.
            - *payload* (optional): an optional payload from the caller.
        on_change (Callable): The function that is called when a control
            modifies variables it is bound to, as the result of an interaction with the
            end-user.<br/>
            It defaults to the `on_change()` global function defined in the Python
            application. If there is no such function, user interactions will not trigger
            anything.<br/>
            The signature of the *on_change* callback function must be:

            - *state*: the `State^` instance of the caller.
            - *var_name* (str): The name of the variable that triggered this callback.
            - *var_value* (any): The new value for this variable.
        on_init (Callable): The function that is called on the first connection of a new client.<br/>
            It defaults to the `on_init()` global function defined in the Python
            application. If there is no such function, the first connection will not trigger
            anything.<br/>

            The signature of the *on_init* callback function must be:

            - *state*: the `State^` instance of the caller.
        on_navigate (Callable): The function that is called when a page is requested.<br/>
            It defaults to the `on_navigate()` global function defined in the Python
            application. If there is no such function, page requests will not trigger
            anything.<br/>
            The signature of the *on_navigate* callback function must be:

            - *state*: the `State^` instance of the caller.
            - *page_name*: the name of the page the user is navigating to.

            The *on_navigate* callback function must return the name of the page the user should be
            directed to.
        on_exception (Callable): The function that is called an exception occurs on user code.<br/>
            It defaults to the `on_exception()` global function defined in the Python
            application. If there is no such function, exceptions will not trigger
            anything.<br/>
            The signature of the *on_exception* callback function must be:

            - *state*: the `State^` instance of the caller.
            - *function_name*: the name of the function that raised the exception.
            - *exception*: the exception object that was raised.
        on_status (Callable): The function that is called when the status page is shown.<br/>
            It defaults to the `on_status()` global function defined in the Python
            application. If there is no such function, status page content shows only the status of the
            server.<br/>
            The signature of the *on_status* callback function must be:

            - *state*: the `State^` instance of the caller.

            It must return raw and valid HTML content as a string.
        on_user_content (Callable): The function that is called when a specific URL (generated by `get_user_content_url()^`) is requested.<br/>
            It defaults to the `on_user_content()` global function defined in the Python
            application. If there is no such function, those specific URL will not trigger
            anything.<br/>
            The signature of the *on_user_content* callback function must be:

            - *state*: the `State^` instance of the caller.
            - *path*: the path provided to the `get_user_content_url()^` to build the URL.
            - *query_args*: An optional dictionnary as defined in the `get_user_content_url()^` call.

            The *on_user_content* callback function must return the raw HTML content of the page to be displayed by the browser.

        state (State^): **Only defined when running in an IPython notebook context.**<br/>
            The unique instance of `State^` that you can use to change bound variables
            directly, potentially impacting the user interface in real-time.

    !!! note
        This class belongs to and is documented in the `taipy.gui` package but it is
        accessible from the top `taipy` package to simplify its access, allowing to
        use:
        ```py
        from taipy import Gui
        ```
    """

    __root_page_name = "TaiPy_root_page"
    __env_filename = "taipy.gui.env"
    __UI_BLOCK_NAME = "TaipyUiBlockVar"
    __MESSAGE_GROUPING_NAME = "TaipyMessageGrouping"
    __ON_INIT_NAME = "TaipyOnInit"
    __ARG_CLIENT_ID = "client_id"
    __INIT_URL = "taipy-init"
    __JSX_URL = "taipy-jsx"
    __CONTENT_ROOT = "taipy-content"
    __UPLOAD_URL = "taipy-uploads"
    _EXTENSION_ROOT = "taipy-extension"
    __USER_CONTENT_URL = "taipy-user-content"
    __SELF_VAR = "__gui"
    __DO_NOT_UPDATE_VALUE = _DoNotUpdate()

    __RE_HTML = re.compile(r"(.*?)\.html")
    __RE_MD = re.compile(r"(.*?)\.md")
    __RE_PAGE_NAME = re.compile(r"^[\w\-\/]+$")

    __reserved_routes: t.List[str] = [
        __INIT_URL,
        __JSX_URL,
        __CONTENT_ROOT,
        __UPLOAD_URL,
        _EXTENSION_ROOT,
        __USER_CONTENT_URL,
    ]

    __LOCAL_TZ = str(tzlocal.get_localzone())

    __extensions: t.Dict[str, t.List[ElementLibrary]] = {}

    def __init__(
        self,
        page: t.Optional[t.Union[str, Page]] = None,
        pages: t.Optional[dict] = None,
        css_file: t.Optional[str] = None,
        path_mapping: t.Optional[dict] = {},
        env_filename: t.Optional[str] = None,
        libraries: t.Optional[t.List[ElementLibrary]] = None,
        flask: t.Optional[Flask] = None,
    ):
        """Initialize a new Gui instance.

        Arguments:
            page (Optional[Union[str, Page^]]): An optional `Page^` instance that is used
                when there is a single page in this interface, referenced as the _root_
                page (located at `/`).<br/>
                If _page_ is a raw string and if it holds a path to a readable file then
                a `Markdown^` page is built from the content of that file.<br/>
                If _page_ is a string that does not indicate a path to readable file then
                a `Markdown^` page is built from that string.<br/>
                Note that if _pages_ is provided, those pages are added as well.
            pages (Optional[dict]): Used if you want to initialize this instance with a set
                of pages.<br/>
                The method `(Gui.)add_pages(pages)^` is called if _pages_ is not None.
                You can find details on the possible values of this argument in the
                documentation for this method.
            css_file (Optional[str]): A pathname to a CSS file that gets used as a style sheet in
                all the pages.<br/>
                The default value is a file that has the same base name as the Python
                file defining the `main` function, sitting next to this Python file,
                with the `.css` extension.
            path_mapping (Optional[dict]): A dictionary that associates a URL prefix to
                a path in the server file system.<br/>
                If the assets of your application are located in _/home/me/app_assets_ and
                you want to access them using only '_assets_' in your application, you can
                set _path_mapping={"assets": "/home/me/app_assets"}_. If your application
                then requests the file _"/assets/images/logo.png"_, the server searches
                for the file  _"/home/me/app_assets/images/logo.png"_.<br/>
                If empty or not defined, access through the browser to all resources under the directory of the main python file
                is allowed.
            env_filename (Optional[str]): An optional file from which to load application
                configuration variables (see the
                [Configuration](../gui/configuration.md#configuring-the-gui-instance) section
                of the User Manual for details.)<br/>
                The default value is "taipy.gui.env"
            libraries (Optional[List[ElementLibrary]]): An optional list of extension library
                instances that pages can reference.<br/>
                Using this argument is equivalent to calling `(Gui.)add_library()^` for each
                list's elements.
            flask (Optional[Flask]): An optional instance of a Flask application object.<br/>
                If this argument is set, this `Gui` instance will use the value of this argument
                as the underlying server. If omitted or set to None, this `Gui` will create its
                own Flask application instance and use it to serve the pages.
        """
        # store suspected local containing frame
        self.__frame = t.cast(FrameType, t.cast(FrameType, inspect.currentframe()).f_back)
        self.__default_module_name = _get_module_name_from_frame(self.__frame)

        # Preserve server config for server initialization
        self._path_mapping = path_mapping
        self._flask = flask
        if css_file is None:
            script_file = pathlib.Path(self.__frame.f_code.co_filename or ".").resolve()
            if script_file.with_suffix(".css").exists():
                css_file = f"{script_file.stem}.css"
            elif script_file.is_dir() and (script_file / "taipy.css").exists():
                css_file = "taipy.css"
        self.__css_file = css_file

        self._config = _Config()
        self.__content_accessor = None
        self._accessors = _DataAccessors()
        self.__state: t.Optional[State] = None
        self.__bindings = _Bindings(self)
        self.__locals_context = _LocalsContext()
        self.__var_dir = _VariableDirectory(self.__locals_context)

        self.__evaluator: _Evaluator = None  # type: ignore
        self.__adapter = _Adapter()
        self.__directory_name_of_pages: t.List[str] = []

        # default actions
        self.on_action: t.Optional[t.Callable] = None
        self.on_change: t.Optional[t.Callable] = None
        self.on_init: t.Optional[t.Callable] = None
        self.on_navigate: t.Optional[t.Callable] = None
        self.on_exception: t.Optional[t.Callable] = None
        self.on_status: t.Optional[t.Callable] = None
        self.on_user_content: t.Optional[t.Callable] = None

        # sid from client_id
        self.__client_id_2_sid: t.Dict[str, t.Set[str]] = {}

        # Load default config
        self._flask_blueprint: t.List[Blueprint] = []
        self._config._load(default_config)

        # get taipy version
        try:
            gui_file = pathlib.Path(__file__ or ".").resolve()
            with open(gui_file.parent / "version.json") as version_file:
                self.__version = json.load(version_file)
        except Exception as e:  # pragma: no cover
            _warn(f"Cannot retrieve version.json file:\n{e}")
            self.__version = {}

        # Load Markdown extension
        # NOTE: Make sure, if you change this extension list, that the User Manual gets updated.
        # There's a section that explicitly lists these extensions in
        #      docs/gui/pages.md#markdown-specifics
        self._markdown = md_lib.Markdown(
            extensions=[
                "fenced_code",
                "meta",
                "admonition",
                "sane_lists",
                "tables",
                "attr_list",
                "md_in_html",
                _TaipyMarkdownExtension(gui=self),
            ]
        )

        if page:
            self.add_page(name=Gui.__root_page_name, page=page)
        if pages is not None:
            self.add_pages(pages)
        if env_filename is not None:
            self.__env_filename = env_filename
        if libraries is not None:
            for library in libraries:
                Gui.add_library(library)

    @staticmethod
    def add_library(library: ElementLibrary) -> None:
        """Add a custom visual element library.

        This application will be able to use custom visual elements defined in this library.

        Arguments:
            library: The custom visual element library to add to this application.

        Multiple libraries with the same name can be added. This allows to split multiple custom visual elements
        in several `ElementLibrary^` instances, but still refer to these elements with the same prefix in the page
        definitions.
        """
        if isinstance(library, ElementLibrary):
            _Factory.set_library(library)
            library_name = library.get_name()
            if library_name.isidentifier():
                libs = Gui.__extensions.get(library_name)
                if libs is None:
                    Gui.__extensions[library_name] = [library]
                else:
                    libs.append(library)
            else:
                raise NameError(f"ElementLibrary passed to add_library() has an invalid name: '{library_name}'")
        else:  # pragma: no cover
            raise RuntimeError(
                f"add_library() argument should be a subclass of ElementLibrary instead of '{type(library)}'"
            )

    def __get_content_accessor(self):
        if self.__content_accessor is None:
            self.__content_accessor = _ContentAccessor(self._get_config("data_url_max_size", 50 * 1024))
        return self.__content_accessor

    def _bindings(self):
        return self.__bindings

    def _get_data_scope(self):
        return self.__bindings._get_data_scope()

    def _get_config(self, name: ConfigParameter, default_value: t.Any) -> t.Any:
        return self._config._get_config(name, default_value)

    def _get_themes(self) -> t.Optional[t.Dict[str, t.Any]]:
        theme = self._get_config("theme", None)
        dark_theme = self._get_config("dark_theme", None)
        light_theme = self._get_config("light_theme", None)
        res = {}
        if theme:
            res["base"] = theme
        if dark_theme:
            res["dark"] = dark_theme
        if light_theme:
            res["light"] = light_theme
        return res if theme or dark_theme or light_theme else None

    def _bind(self, name: str, value: t.Any) -> None:
        self._bindings()._bind(name, value)

    def __get_state(self):
        return self.__state

    def _get_client_id(self) -> str:
        return (
            _DataScopes._GLOBAL_ID
            if self._bindings()._get_single_client()
            else getattr(g, Gui.__ARG_CLIENT_ID, "unknown id")
        )

    def __set_client_id_in_context(self, client_id: t.Optional[str] = None):
        if not client_id and request:
            client_id = request.args.get(Gui.__ARG_CLIENT_ID, "")
        if client_id and request:
            if sid := getattr(request, "sid", None):
                sids = self.__client_id_2_sid.get(client_id, None)
                if sids is None:
                    sids = set()
                    self.__client_id_2_sid[client_id] = sids
                sids.add(sid)
        g.client_id = client_id

    def __is_var_modified_in_context(self, var_name: str, derived_vars: t.Set[str]) -> bool:
        modified_vars: t.Optional[t.Set[str]] = getattr(g, "modified_vars", None)
        der_vars: t.Optional[t.Set[str]] = getattr(g, "derived_vars", None)
        setattr(g, "update_count", getattr(g, "update_count", 0) + 1)
        if modified_vars is None:
            modified_vars = set()
            g.modified_vars = modified_vars
        if der_vars is None:
            g.derived_vars = derived_vars
        else:
            der_vars.update(derived_vars)
        if var_name in modified_vars:
            return True
        modified_vars.add(var_name)
        return False

    def __clean_vars_on_exit(self) -> t.Optional[t.Set[str]]:
        update_count = getattr(g, "update_count", 0) - 1
        if update_count < 1:
            derived_vars: t.Set[str] = getattr(g, "derived_vars", set())
            delattr(g, "update_count")
            delattr(g, "modified_vars")
            delattr(g, "derived_vars")
            return derived_vars
        else:
            setattr(g, "update_count", update_count)
            return None

    def _manage_message(self, msg_type: _WsType, message: dict) -> None:
        try:
            self.__set_client_id_in_context(message.get(Gui.__ARG_CLIENT_ID))
            self._set_locals_context(message.get("module_context") or None)
            if msg_type == _WsType.UPDATE.value:
                payload = message.get("payload", {})
                self.__front_end_update(
                    str(message.get("name")),
                    payload.get("value"),
                    message.get("propagate", True),
                    payload.get("relvar"),
                    payload.get("on_change"),
                )
            elif msg_type == _WsType.ACTION.value:
                self.__on_action(message.get("name"), message.get("payload"))
            elif msg_type == _WsType.DATA_UPDATE.value:
                self.__request_data_update(str(message.get("name")), message.get("payload"))
            elif msg_type == _WsType.REQUEST_UPDATE.value:
                self.__request_var_update(message.get("payload"))
            elif msg_type == _WsType.CLIENT_ID.value:
                self._bindings()._get_or_create_scope(message.get("payload", ""))
            self._reset_locals_context()
            self.__send_ack(message.get("ack_id"))
        except Exception as e:  # pragma: no cover
            _warn(f"Decoding Message has failed: {message}\n{e}")

    def __front_end_update(
        self,
        var_name: str,
        value: t.Any,
        propagate=True,
        rel_var: t.Optional[str] = None,
        on_change: t.Optional[str] = None,
    ) -> None:
        if not var_name:
            return
        # Check if Variable is a managed type
        current_value = _getscopeattr_drill(self, self.__evaluator.get_hash_from_expr(var_name))
        if isinstance(current_value, _TaipyData):
            return
        elif rel_var and isinstance(current_value, _TaipyLovValue):  # pragma: no cover
            lov_holder = _getscopeattr_drill(self, self.__evaluator.get_hash_from_expr(rel_var))
            if isinstance(lov_holder, _TaipyLov):
                val = value if isinstance(value, list) else [value]
                elt_4_ids = self.__adapter._get_elt_per_ids(lov_holder.get_name(), lov_holder.get())
                ret_val = [elt_4_ids.get(x, x) for x in val]
                if isinstance(value, list):
                    value = ret_val
                elif ret_val:
                    value = ret_val[0]
        elif isinstance(current_value, _TaipyBase):
            value = current_value.cast_value(value)
        self._update_var(
            var_name, value, propagate, current_value if isinstance(current_value, _TaipyBase) else None, on_change
        )

    def _update_var(
        self,
        var_name: str,
        value: t.Any,
        propagate=True,
        holder: t.Optional[_TaipyBase] = None,
        on_change: t.Optional[str] = None,
    ) -> None:
        if holder:
            var_name = holder.get_name()
        hash_expr = self.__evaluator.get_hash_from_expr(var_name)
        derived_vars = {hash_expr}
        # Use custom attrsetter function to allow value binding for _MapDict
        if propagate:
            _setscopeattr_drill(self, hash_expr, value)
            # In case expression == hash (which is when there is only a single variable in expression)
            if var_name == hash_expr or hash_expr.startswith("tpec_"):
                derived_vars.update(self._re_evaluate_expr(var_name))
        elif holder:
            derived_vars.update(self._evaluate_holders(hash_expr))
        # if the variable has been evaluated then skip updating to prevent infinite loop
        var_modified = self.__is_var_modified_in_context(hash_expr, derived_vars)
        if not var_modified:
            self._call_on_change(
                var_name,
                value.get() if isinstance(value, _TaipyBase) else value._dict if isinstance(value, _MapDict) else value,
                on_change,
            )
        derived_modified = self.__clean_vars_on_exit()
        if derived_modified is not None:
            self.__send_var_list_update(list(derived_modified), var_name)

    def _get_real_var_name(self, var_name: str) -> t.Tuple[str, str]:
        if not var_name:
            return (var_name, var_name)
        # Handle holder prefix if needed
        if var_name.startswith(_TaipyBase._HOLDER_PREFIX):
            for hp in _TaipyBase._get_holder_prefixes():
                if var_name.startswith(hp):
                    var_name = var_name[len(hp) :]
                    break
        suffix_var_name = ""
        if "." in var_name:
            first_dot_index = var_name.index(".")
            suffix_var_name = var_name[first_dot_index + 1 :]
            var_name = var_name[:first_dot_index]
        var_name_decode, module_name = _variable_decode(self._get_expr_from_hash(var_name))
        current_context = self._get_locals_context()
        # #583: allow module resolution for var_name in current_context root_page context
        if (
            module_name
            and self._config.root_page
            and self._config.root_page._renderer
            and self._config.root_page._renderer._get_module_name() == module_name
        ):
            return f"{var_name_decode}.{suffix_var_name}" if suffix_var_name else var_name_decode, module_name
        if module_name == current_context:
            var_name = var_name_decode
        else:
            if var_name not in self.__var_dir._var_head:
                raise NameError(f"Can't find matching variable for {var_name} on context: {current_context}")
            _found = False
            for k, v in self.__var_dir._var_head[var_name]:
                if v == current_context:
                    var_name = k
                    _found = True
                    break
            if not _found:  # pragma: no cover
                raise NameError(f"Can't find matching variable for {var_name} on context: {current_context}")
        return f"{var_name}.{suffix_var_name}" if suffix_var_name else var_name, current_context

    def _call_on_change(self, var_name: str, value: t.Any, on_change: t.Optional[str] = None):
        try:
            var_name, current_context = self._get_real_var_name(var_name)
        except Exception as e:  # pragma: no cover
            _warn(f"{e}")
            return
        on_change_fn = self._get_user_function(on_change) if on_change else None
        if not callable(on_change_fn):
            on_change_fn = self._get_user_function("on_change")
        if callable(on_change_fn):
            try:
                argcount = on_change_fn.__code__.co_argcount
                if argcount > 0 and inspect.ismethod(on_change_fn):
                    argcount -= 1
                args: t.List[t.Any] = [None for _ in range(argcount)]
                if argcount > 0:
                    args[0] = self.__get_state()
                if argcount > 1:
                    args[1] = var_name
                if argcount > 2:
                    args[2] = value
                if argcount > 3:
                    args[3] = current_context
                on_change_fn(*args)
            except Exception as e:  # pragma: no cover
                if not self._call_on_exception(on_change or "on_change", e):
                    _warn(f"{on_change or 'on_change'}(): callback function raised an exception:\n{e}")

    def _get_content(self, var_name: str, value: t.Any, image: bool) -> t.Any:
        ret_value = self.__get_content_accessor().get_info(var_name, value, image)
        return f"/{Gui.__CONTENT_ROOT}/{ret_value[0]}" if isinstance(ret_value, tuple) else ret_value

    def __serve_content(self, path: str) -> t.Any:
        self.__set_client_id_in_context()
        parts = path.split("/")
        if len(parts) > 1:
            file_name = parts[-1]
            (dir_path, as_attachment) = self.__get_content_accessor().get_content_path(
                path[: -len(file_name) - 1], file_name, request.args.get("bypass")
            )
            if dir_path:
                return send_from_directory(str(dir_path), file_name, as_attachment=as_attachment)
        return ("", 404)

    def _get_user_content_url(
        self, path: t.Optional[str] = None, query_args: t.Optional[t.Dict[str, str]] = None
    ) -> t.Optional[str]:
        qargs = query_args or {}
        qargs.update({Gui.__ARG_CLIENT_ID: self._get_client_id()})
        return f"/{Gui.__USER_CONTENT_URL}/{path or ''}?{urlencode(qargs)}"

    def __serve_user_content(self, path: str) -> t.Any:
        if hasattr(self, "on_user_content") and callable(self.on_user_content):
            self.__set_client_id_in_context()
            try:
                qargs: t.Dict[str, str] = {}
                qargs.update(request.args)
                qargs.pop(Gui.__ARG_CLIENT_ID, None)
                args: t.List[t.Any] = []
                if path:
                    args.append(path)
                if len(qargs):
                    args.append(qargs)
                ret = self._call_function_with_state(self.on_user_content, args)
                if ret is None:
                    _warn("on_user_content() callback function should return a value.")
                else:
                    return (ret, 200)
            except Exception as e:  # pragma: no cover
                if not self._call_on_exception("on_user_content", e):
                    _warn(f"on_user_content() callback function raised an exception:\n{e}")
        else:
            _warn("on_user_content() callback function has not been defined.")
        return ("", 404)

    def __serve_extension(self, path: str) -> t.Any:
        parts = path.split("/")
        last_error = ""
        resource_name = None
        if len(parts) > 1:
            libs = Gui.__extensions.get(parts[0], [])
            for library in libs:
                try:
                    resource_name = library.get_resource("/".join(parts[1:]))
                    if resource_name:
                        return send_file(resource_name)
                except Exception as e:
                    last_error = f"\n{e}"  # Check if the resource is served by another library with the same name
        _warn(f"Resource '{resource_name or path}' not accessible for library '{parts[0]}'{last_error}")
        return ("", 404)

    def __get_version(self) -> str:
        return f'{self.__version.get("major", 0)}.{self.__version.get("minor", 0)}.{self.__version.get("patch", 0)}'

    def __append_libraries_to_status(self, status: t.Dict[str, t.Any]):
        libraries: t.Dict[str, t.Any] = {}
        for libs_list in self.__extensions.values():
            for lib in libs_list:
                if not isinstance(lib, ElementLibrary):
                    continue
                libs = libraries.get(lib.get_name())
                if libs is None:
                    libs = []
                    libraries[lib.get_name()] = libs
                elts: t.List[t.Dict[str, str]] = []
                libs.append({"js module": lib.get_js_module_name(), "elements": elts})
                for element_name, elt in lib.get_elements().items():
                    if not isinstance(elt, Element):
                        continue
                    elt_dict = {"name": element_name}
                    if hasattr(elt, "_render_xhtml"):
                        elt_dict["render function"] = elt._render_xhtml.__code__.co_name
                    else:
                        elt_dict["react name"] = elt._get_js_name(element_name)
                    elts.append(elt_dict)
        status.update({"libraries": libraries})

    def _serve_status(self, template: pathlib.Path) -> t.Dict[str, t.Dict[str, str]]:
        base_json: t.Dict[str, t.Any] = {"user_status": str(self.__call_on_status() or "")}
        if self._get_config("extended_status", False):
            base_json.update(
                {
                    "flask_version": str(flask_version or ""),
                    "backend_version": self.__get_version(),
                    "host": f'{self._get_config("host", "localhost")}:{self._get_config("port", "default")}',
                    "python_version": sys.version,
                }
            )
            self.__append_libraries_to_status(base_json)
            try:
                base_json.update(json.loads(template.read_text()))
            except Exception as e:  # pragma: no cover
                _warn(f"Exception raised reading JSON in '{template}':\n{e}")
        return {"gui": base_json}

    def __upload_files(self):
        self.__set_client_id_in_context()
        if "var_name" not in request.form:
            _warn("No var name")
            return ("No var name", 400)
        var_name = request.form["var_name"]
        multiple = "multiple" in request.form and request.form["multiple"] == "True"
        if "blob" not in request.files:
            _warn("No file part")
            return ("No file part", 400)
        file = request.files["blob"]
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == "":
            _warn("No selected file")
            return ("No selected file", 400)
        suffix = ""
        complete = True
        part = 0
        if "total" in request.form:
            total = int(request.form["total"])
            if total > 1 and "part" in request.form:
                part = int(request.form["part"])
                suffix = f".part.{part}"
                complete = part == total - 1
        if file:  # and allowed_file(file.filename)
            upload_path = pathlib.Path(self._get_config("upload_folder", tempfile.gettempdir())).resolve()
            file_path = _get_non_existent_file_path(upload_path, secure_filename(file.filename))
            file.save(str(upload_path / (file_path.name + suffix)))
            if complete:
                if part > 0:
                    try:
                        with open(file_path, "wb") as grouped_file:
                            for nb in range(part + 1):
                                with open(upload_path / f"{file_path.name}.part.{nb}", "rb") as part_file:
                                    grouped_file.write(part_file.read())
                    except EnvironmentError as ee:  # pragma: no cover
                        _warn(f"Cannot group file after chunk upload:\n{ee}")
                        return
                # notify the file is uploaded
                newvalue = str(file_path)
                if multiple:
                    value = _getscopeattr(self, var_name)
                    if not isinstance(value, t.List):
                        value = [] if value is None else [value]
                    value.append(newvalue)
                    newvalue = value
                setattr(self._bindings(), var_name, newvalue)
        return ("", 200)

    def __send_var_list_update(
        self,
        modified_vars: t.List[str],
        front_var: t.Optional[str] = None,
    ):
        ws_dict = {}
        values = {v: _getscopeattr_drill(self, v) for v in modified_vars}
        for k, v in values.items():
            if isinstance(v, _TaipyData) and v.get_name() in modified_vars:
                modified_vars.remove(v.get_name())
            elif isinstance(v, _DoNotUpdate):
                modified_vars.remove(k)
        for _var in modified_vars:
            newvalue = values.get(_var)
            # self._scopes.broadcast_data(_var, newvalue)
            if isinstance(newvalue, _TaipyData):
                newvalue = None
            else:
                if isinstance(newvalue, (_TaipyContent, _TaipyContentImage)):
                    ret_value = self.__get_content_accessor().get_info(
                        front_var, newvalue.get(), isinstance(newvalue, _TaipyContentImage)
                    )
                    if isinstance(ret_value, tuple):
                        newvalue = f"/{Gui.__CONTENT_ROOT}/{ret_value[0]}"
                    else:
                        newvalue = ret_value
                elif isinstance(newvalue, _TaipyLov):
                    newvalue = [self.__adapter._run_for_var(newvalue.get_name(), elt) for elt in newvalue.get()]
                elif isinstance(newvalue, _TaipyLovValue):
                    if isinstance(newvalue.get(), list):
                        newvalue = [
                            self.__adapter._run_for_var(newvalue.get_name(), elt, id_only=True)
                            for elt in newvalue.get()
                        ]
                    else:
                        newvalue = self.__adapter._run_for_var(newvalue.get_name(), newvalue.get(), id_only=True)
                if isinstance(newvalue, (dict, _MapDict)):
                    continue  # this var has no transformer
                debug_warnings: t.List[warnings.WarningMessage] = []
                with warnings.catch_warnings(record=True) as warns:
                    warnings.resetwarnings()
                    json.dumps(newvalue, cls=_TaipyJsonEncoder)
                    if len(warns):
                        keep_value = True
                        for w in list(warns):
                            if is_debugging():
                                debug_warnings.append(w)
                            if w.category is not DeprecationWarning and w.category is not PendingDeprecationWarning:
                                keep_value = False
                                break
                        if not keep_value:
                            # do not send data that is not serializable
                            continue
                for w in debug_warnings:
                    warnings.warn(w.message, w.category)
            ws_dict[_var] = newvalue
        # TODO: What if value == newvalue?
        self.__send_ws_update_with_dict(ws_dict)

    def __request_data_update(self, var_name: str, payload: t.Any) -> None:
        # Use custom attrgetter function to allow value binding for _MapDict
        newvalue = _getscopeattr_drill(self, var_name)
        if isinstance(newvalue, _TaipyData):
            ret_payload = None
            if isinstance(payload, dict):
                lib_name = payload.get("library")
                if isinstance(lib_name, str):
                    libs = self.__extensions.get(lib_name, [])
                    for lib in libs:
                        user_var_name = var_name
                        try:
                            with contextlib.suppress(NameError):
                                # ignore name error and keep var_name
                                user_var_name = self._get_real_var_name(var_name)[0]
                            ret_payload = lib.get_data(lib_name, payload, user_var_name, newvalue)
                            if ret_payload:
                                break
                        except Exception as e:  # pragma: no cover
                            _warn(
                                f"Exception raised in '{lib_name}.get_data({lib_name}, payload, {user_var_name}, value)':\n{e}"
                            )
            if not isinstance(ret_payload, dict):
                ret_payload = self._accessors._get_data(self, var_name, newvalue, payload)
            self.__send_ws_update_with_dict({var_name: ret_payload})

    def __request_var_update(self, payload: t.Any):
        if isinstance(payload, dict) and isinstance(payload.get("names"), list):
            if payload.get("refresh", False):
                # refresh vars
                for _var in t.cast(list, payload.get("names")):
                    val = _getscopeattr_drill(self, _var)
                    self._refresh_expr(
                        val.get_name() if isinstance(val, _TaipyBase) else _var,
                        val if isinstance(val, _TaipyBase) else None,
                    )
            self.__send_var_list_update(payload["names"])

    def __send_ws(self, payload: dict) -> None:
        grouping_message = self.__get_message_grouping()
        if grouping_message is None:
            try:
                self._server._ws.emit(
                    "message",
                    payload,
                    to=self.__get_ws_receiver(),
                )
                time.sleep(0.001)
            except Exception as e:  # pragma: no cover
                _warn(f"Exception raised in Web Socket communication in '{self.__frame.f_code.co_name}':\n{e}")
        else:
            grouping_message.append(payload)

    def __broadcast_ws(self, payload: dict):
        try:
            self._server._ws.emit(
                "message",
                payload,
            )
            time.sleep(0.001)
        except Exception as e:  # pragma: no cover
            _warn(f"Exception raised in Web Socket communication in '{self.__frame.f_code.co_name}':\n{e}")

    def __send_ack(self, ack_id: t.Optional[str]) -> None:
        if ack_id:
            try:
                self._server._ws.emit("message", {"type": _WsType.ACKNOWLEDGEMENT.value, "id": ack_id})
                time.sleep(0.001)
            except Exception as e:  # pragma: no cover
                _warn(
                    f"Exception raised in Web Socket communication (send ack) in '{self.__frame.f_code.co_name}':\n{e}"
                )

    def _send_ws_id(self, id: str) -> None:
        self.__send_ws(
            {
                "type": _WsType.CLIENT_ID.value,
                "id": id,
            }
        )

    def __send_ws_download(self, content: str, name: str, on_action: str) -> None:
        self.__send_ws({"type": _WsType.DOWNLOAD_FILE.value, "content": content, "name": name, "on_action": on_action})

    def __send_ws_alert(self, type: str, message: str, system_notification: bool, duration: int) -> None:
        self.__send_ws(
            {
                "type": _WsType.ALERT.value,
                "atype": type,
                "message": message,
                "system": system_notification,
                "duration": duration,
            }
        )

    def __send_ws_partial(self, partial: str):
        self.__send_ws(
            {
                "type": _WsType.PARTIAL.value,
                "name": partial,
            }
        )

    def __send_ws_block(
        self,
        action: t.Optional[str] = None,
        message: t.Optional[str] = None,
        close: t.Optional[bool] = False,
        cancel: t.Optional[bool] = False,
    ):
        self.__send_ws(
            {
                "type": _WsType.BLOCK.value,
                "action": action,
                "close": close,
                "message": message,
                "noCancel": not cancel,
            }
        )

    def __send_ws_navigate(
        self,
        to: str,
        tab: t.Optional[str],
        force: bool,
    ):
        self.__send_ws({"type": _WsType.NAVIGATE.value, "to": to, "tab": tab, "force": force})

    def __send_ws_update_with_dict(self, modified_values: dict) -> None:
        payload = [
            {"name": _get_client_var_name(k), "payload": (v if isinstance(v, dict) and "value" in v else {"value": v})}
            for k, v in modified_values.items()
        ]
        self.__send_ws({"type": _WsType.MULTIPLE_UPDATE.value, "payload": payload})

    def __send_ws_broadcast(self, var_name: str, var_value: t.Any):
        self.__broadcast_ws(
            {"type": _WsType.UPDATE.value, "name": _get_broadcast_var_name(var_name), "payload": {"value": var_value}}
        )

    def __get_ws_receiver(self) -> t.Union[t.List[str], t.Any, None]:
        if self._bindings()._get_single_client():
            return None
        sid = getattr(request, "sid", None) if request else None
        sids = self.__client_id_2_sid.get(self._get_client_id(), set())
        if sid:
            sids.add(sid)
        return list(sids)

    def __get_message_grouping(self):
        return (
            _getscopeattr(self, Gui.__MESSAGE_GROUPING_NAME)
            if _hasscopeattr(self, Gui.__MESSAGE_GROUPING_NAME)
            else None
        )

    def __enter__(self):
        self.__hold_messages()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.__send_messages()
        except Exception as e:  # pragma: no cover
            _warn(f"Exception raised while sending messages:\n{e}")
        if exc_value:  # pragma: no cover
            _warn(f"An {exc_type or 'Exception'} was raised: {exc_value}.")
        return True

    def __hold_messages(self):
        grouping_message = self.__get_message_grouping()
        if grouping_message is None:
            self._bind_var_val(Gui.__MESSAGE_GROUPING_NAME, [])

    def __send_messages(self):
        grouping_message = self.__get_message_grouping()
        if grouping_message is not None:
            _delscopeattr(self, Gui.__MESSAGE_GROUPING_NAME)
            if len(grouping_message):
                self.__send_ws({"type": _WsType.MULTIPLE_MESSAGE.value, "payload": grouping_message})

    def _get_user_function(self, func_name: str) -> t.Union[t.Callable, str]:
        func = _getscopeattr(self, func_name, None)
        if not callable(func):
            func = self._get_locals_bind().get(func_name)
        if not callable(func):
            func = self.__locals_context.get_default().get(func_name)
        return func if callable(func) else func_name

    def _get_user_instance(self, class_name: str, class_type: type) -> t.Union[object, str]:
        cls = _getscopeattr(self, class_name, None)
        if not isinstance(cls, class_type):
            cls = self._get_locals_bind().get(class_name)
        if not isinstance(cls, class_type):
            cls = self.__locals_context.get_default().get(class_name)
        return cls if isinstance(cls, class_type) else class_name

    def __on_action(self, id: t.Optional[str], payload: t.Any) -> None:
        action = payload.get("action") if isinstance(payload, dict) else str(payload)
        if action:
            if self.__call_function_with_args(
                action_function=self._get_user_function(action), id=id, payload=payload, action=action
            ):
                return
            else:  # pragma: no cover
                _warn(f"on_action(): '{action}' is not a valid function.")
        if hasattr(self, "on_action"):
            self.__call_function_with_args(action_function=self.on_action, id=id, payload=payload, action=action)

    def __call_function_with_args(self, **kwargs):
        action_function = kwargs.get("action_function")
        id = kwargs.get("id")
        action = kwargs.get("action")
        payload = kwargs.get("payload")

        if callable(action_function):
            try:
                argcount = action_function.__code__.co_argcount
                if argcount > 0 and inspect.ismethod(action_function):
                    argcount -= 1
                args = [None for _ in range(argcount)]
                if argcount > 0:
                    args[0] = self.__get_state()
                if argcount > 1:
                    try:
                        args[1] = self._get_real_var_name(id)[0]
                    except Exception:
                        args[1] = id
                if argcount > 2:
                    args[2] = payload if action is None else action
                if argcount > 3 and action is not None:
                    args[3] = payload
                action_function(*args)
                return True
            except Exception as e:  # pragma: no cover
                if not self._call_on_exception(action_function.__name__, e):
                    _warn(f"on_action(): Exception raised in '{action_function.__name__}()':\n{e}")
        return False

    def _call_function_with_state(self, user_function: t.Callable, args: t.List[t.Any]) -> t.Any:
        args.insert(0, self.__get_state())
        argcount = user_function.__code__.co_argcount
        if argcount > 0 and inspect.ismethod(user_function):
            argcount -= 1
        if argcount > len(args):
            args += (argcount - len(args)) * [None]
        else:
            args = args[:argcount]
        return user_function(*args)

    def _call_user_callback(
        self, state_id: t.Optional[str], user_callback: t.Callable, args: t.List[t.Any], module_context: t.Optional[str]
    ) -> t.Any:
        try:
            with self.get_flask_app().app_context():
                self.__set_client_id_in_context(state_id)
                if module_context is not None:
                    self._set_locals_context(module_context)
                return self._call_function_with_state(user_callback, args)
        except Exception as e:  # pragma: no cover
            if not self._call_on_exception(user_callback.__name__, e):
                _warn(f"invoke_callback(): Exception raised in '{user_callback.__name__}()':\n{e}")
        return None

    # Proxy methods for Evaluator
    def _evaluate_expr(self, expr: str) -> t.Any:
        return self.__evaluator.evaluate_expr(self, expr)

    def _re_evaluate_expr(self, var_name: str) -> t.Set[str]:
        return self.__evaluator.re_evaluate_expr(self, var_name)

    def _refresh_expr(self, var_name: str, holder: t.Optional[_TaipyBase]):
        return self.__evaluator.refresh_expr(self, var_name, holder)

    def _get_expr_from_hash(self, hash_val: str) -> str:
        return self.__evaluator.get_expr_from_hash(hash_val)

    def _evaluate_bind_holder(self, holder: t.Type[_TaipyBase], expr: str) -> str:
        return self.__evaluator.evaluate_bind_holder(self, holder, expr)

    def _evaluate_holders(self, expr: str) -> t.List[str]:
        return self.__evaluator.evaluate_holders(self, expr)

    def _is_expression(self, expr: str) -> bool:
        return self.__evaluator._is_expression(expr)

    # make components resettable
    def _set_building(self, building: bool):
        self._building = building

    def __is_building(self):
        return hasattr(self, "_building") and self._building

    def _get_rebuild_fn_name(self, name: str):
        return f"{Gui.__SELF_VAR}.{name}"

    def __get_attributes(self, attr_json: str, hash_json: str, args_dict: t.Dict[str, t.Any]):
        attributes: t.Dict[str, t.Any] = json.loads(unquote(attr_json))
        hashes: t.Dict[str, str] = json.loads(unquote(hash_json))
        attributes.update({k: args_dict.get(v) for k, v in hashes.items()})
        return attributes, hashes

    def _tbl_cols(
        self, rebuild: bool, rebuild_val: t.Optional[bool], attr_json: str, hash_json: str, **kwargs
    ) -> t.Union[str, _DoNotUpdate]:
        if not self.__is_building():
            try:
                rebuild = rebuild_val if rebuild_val is not None else rebuild
                if rebuild:
                    attributes, hashes = self.__get_attributes(attr_json, hash_json, kwargs)
                    data_hash = hashes.get("data", "")
                    data = kwargs.get(data_hash)
                    col_dict = _get_columns_dict(
                        data,
                        attributes.get("columns", {}),
                        self._accessors._get_col_types(data_hash, _TaipyData(data, data_hash)),
                        attributes.get("date_format"),
                        attributes.get("number_format"),
                    )
                    _enhance_columns(attributes, hashes, col_dict, "table(cols)")

                    return json.dumps(col_dict, cls=_TaipyJsonEncoder)
            except Exception as e:  # pragma: no cover
                _warn(f"Exception while rebuilding table columns {e}.")
        return Gui.__DO_NOT_UPDATE_VALUE

    def _chart_conf(
        self, rebuild: bool, rebuild_val: t.Optional[bool], attr_json: str, hash_json: str, **kwargs
    ) -> t.Union[str, _DoNotUpdate]:
        if not self.__is_building():
            try:
                rebuild = rebuild_val if rebuild_val is not None else rebuild
                if rebuild:
                    attributes, hashes = self.__get_attributes(attr_json, hash_json, kwargs)
                    data_hash = hashes.get("data", "")
                    config = _build_chart_config(
                        self,
                        attributes,
                        self._accessors._get_col_types(data_hash, _TaipyData(kwargs.get(data_hash), data_hash)),
                    )

                    return json.dumps(config, cls=_TaipyJsonEncoder)
            except Exception as e:  # pragma: no cover
                _warn(f"Exception while rebuilding chart config {e}.")
        return Gui.__DO_NOT_UPDATE_VALUE

    # Proxy methods for Adapter

    def _add_adapter_for_type(self, type_name: str, adapter: t.Callable) -> None:
        self.__adapter._add_for_type(type_name, adapter)

    def _add_type_for_var(self, var_name: str, type_name: str) -> None:
        self.__adapter._add_type_for_var(var_name, type_name)

    def _get_adapter_for_type(self, type_name: str) -> t.Optional[t.Callable]:
        return self.__adapter._get_for_type(type_name)

    def _get_unique_type_adapter(self, type_name: str) -> str:
        return self.__adapter._get_unique_type(type_name)

    def _run_adapter(
        self, adapter: t.Optional[t.Callable], value: t.Any, var_name: str, id_only=False
    ) -> t.Union[t.Tuple[str, ...], str, None]:
        return self.__adapter._run(adapter, value, var_name, id_only)

    def _get_valid_adapter_result(self, value: t.Any, id_only=False) -> t.Union[t.Tuple[str, ...], str, None]:
        return self.__adapter._get_valid_result(value, id_only)

    def _is_ui_blocked(self):
        return _getscopeattr(self, Gui.__UI_BLOCK_NAME, False)

    def __get_on_cancel_block_ui(self, callback: t.Optional[str]):
        def _taipy_on_cancel_block_ui(guiApp, id: t.Optional[str], payload: t.Any):
            if _hasscopeattr(self, Gui.__UI_BLOCK_NAME):
                _setscopeattr(self, Gui.__UI_BLOCK_NAME, False)
            self.__on_action(id, callback)

        return _taipy_on_cancel_block_ui

    def __add_pages_in_folder(self, folder_name: str, folder_path: str):
        list_of_files = os.listdir(folder_path)
        for file_name in list_of_files:
            from .renderers import Html, Markdown

            if re_match := Gui.__RE_HTML.match(file_name):
                renderers = Html(os.path.join(folder_path, file_name), frame=None)
                renderers.modify_taipy_base_url(folder_name)
                self.add_page(name=f"{folder_name}/{re_match.group(1)}", page=renderers)
            elif re_match := Gui.__RE_MD.match(file_name):
                renderers_md = Markdown(os.path.join(folder_path, file_name), frame=None)
                self.add_page(name=f"{folder_name}/{re_match.group(1)}", page=renderers_md)
            elif os.path.isdir(child_dir_path := os.path.join(folder_path, file_name)):
                child_dir_name = f"{folder_name}/{file_name}"
                self.__add_pages_in_folder(child_dir_name, child_dir_path)

    # Proxy methods for LocalsContext
    def _get_locals_bind(self) -> t.Dict[str, t.Any]:
        return self.__locals_context.get_locals()

    def _get_default_locals_bind(self) -> t.Dict[str, t.Any]:
        return self.__locals_context.get_default()

    def _get_locals_bind_from_context(self, context: t.Optional[str]) -> t.Dict[str, t.Any]:
        return self.__locals_context._get_locals_bind_from_context(context)

    def _get_locals_context(self) -> str:
        current_context = self.__locals_context.get_context()
        return current_context if current_context is not None else self.__default_module_name

    def _set_locals_context(self, context: t.Optional[str]) -> None:
        self.__locals_context.set_locals_context(context)

    def _reset_locals_context(self) -> None:
        self.__locals_context.reset_locals_context()

    def _get_page_context(self, page_name: str) -> str | None:
        if page_name not in self._config.routes:
            return None
        page = None
        for p in self._config.pages:
            if p._route == page_name:
                page = p
        if page is None:
            return None
        return (
            (page._renderer._get_module_name() or self.__default_module_name)
            if page._renderer is not None
            else self.__default_module_name
        )

    @staticmethod
    def _get_root_page_name():
        return Gui.__root_page_name

    def _set_flask(self, flask: Flask):
        self._flask = flask

    def _get_default_module_name(self):
        return self.__default_module_name

    @staticmethod
    def _get_timezone() -> str:
        return Gui.__LOCAL_TZ

    @staticmethod
    def _set_timezone(tz: str):
        Gui.__LOCAL_TZ = tz

    # Public methods
    def add_page(
        self,
        name: str,
        page: t.Union[str, Page],
        style: t.Optional[str] = "",
    ) -> None:
        """Add a page to the Graphical User Interface.

        Arguments:
            name: The name of the page.
            page (Union[str, Page^]): The content of the page.<br/>
                It can be an instance of `Markdown^` or `Html^`.<br/>
                If *page* is a string, then:

                - If *page* is set to the pathname of a readable file, the page
                  content is read as Markdown input text.
                - If it is not, the page content is read from this string as
                  Markdown text.
            style (Optional[str]): Additional CSS style to apply to this page.

                - if there is style associated with a page, it is used at a global level
                - if there is no style associated with the page, the style is cleared at a global level
                - if the page is embedded in a block control, the style is ignored

        Note that page names cannot start with the slash ('/') character and that each
        page must have a unique name.
        """
        # Validate name
        if name is None:  # pragma: no cover
            raise Exception("name is required for add_page() function.")
        if not Gui.__RE_PAGE_NAME.match(name):  # pragma: no cover
            raise SyntaxError(
                f'Page name "{name}" is invalid. It must only contain letters, digits, dash (-), underscore (_), and forward slash (/) characters.'
            )
        if name.startswith("/"):  # pragma: no cover
            raise SyntaxError(f'Page name "{name}" cannot start with forward slash (/) character.')
        if name in self._config.routes:  # pragma: no cover
            raise Exception(f'Page name "{name if name != Gui.__root_page_name else "/"}" is already defined.')
        if isinstance(page, str):
            from .renderers import Markdown

            page = Markdown(page, frame=None)
        elif not isinstance(page, Page):  # pragma: no cover
            raise Exception(
                f'Parameter "page" is invalid for page name "{name if name != Gui.__root_page_name else "/"}.'
            )
        # Init a new page
        new_page = _Page()
        new_page._route = name
        new_page._renderer = page
        new_page._style = style
        # Append page to _config
        self._config.pages.append(new_page)
        self._config.routes.append(name)
        # set root page
        if name == Gui.__root_page_name:
            self._config.root_page = new_page
        # Update locals context
        self.__locals_context.add(page._get_module_name(), page._get_locals())
        # Update variable directory
        self.__var_dir.add_frame(page._frame)

    def add_pages(self, pages: t.Optional[t.Union[t.Dict[str, t.Union[str, Page]], str]] = None) -> None:
        """Add several pages to the Graphical User Interface.

        Arguments:
            pages (Union[dict[str, Union[str, Page^]], str]): The pages to add.<br/>
                If _pages_ is a dictionnary, a page is added to this `Gui` instance
                for each of the entries in _pages_:

                - The entry key is used as the page name.
                - The entry value is used as the page content:
                    - The value can can be an instance of `Markdown^` or `Html^`, then
                      it is used as the page definition.
                    - If entry value is a string, then:
                        - If it is set to the pathname of a readable file, the page
                          content is read as Markdown input text.
                        - If it is not, the page content is read from this string as
                          Markdown text.

        !!! note "Reading pages from a directory"
            If _pages_ is a string that holds the path to a readable directory, then
            this directory is traversed, recursively, to find files that Taipy can build
            pages from.

            For every new directory that is traversed, a new hierarchical level
            for pages is created.

            For every file that is found:

            - If the filename extention is _.md_, it is read as Markdown content and
              a new page is created with the base name of this filename.
            - If the filename extention is _.html_, it is read as HTML content and
              a new page is created with the base name of this filename.

            For example, say you have the following directory structure:
            ```
            reports
            ├── home.html
            ├── budget/
            │   ├── expenses/
            │   │   ├── marketing.md
            │   │   └── production.md
            │   └── revenue/
            │       ├── EMAE.md
            │       ├── USA.md
            │       └── ASIA.md
            └── cashflow/
                ├── weekly.md
                ├── monthly.md
                └── yearly.md
            ```

            Calling `gui.add_pages('reports')` is equivalent to calling:
            ```py
            gui.add_pages({
                            "reports/home", Html("reports/home.html"),
                            "reports/budget/expenses/marketing", Markdown("reports/budget/expenses/marketing.md"),
                            "reports/budget/expenses/production", Markdown("reports/budget/expenses/production.md"),
                            "reports/budget/revenue/EMAE", Markdown("reports/budget/revenue/EMAE.md"),
                            "reports/budget/revenue/USA", Markdown("reports/budget/revenue/USA.md"),
                            "reports/budget/revenue/ASIA", Markdown("reports/budget/revenue/ASIA.md"),
                            "reports/cashflow/weekly", Markdown("reports/cashflow/weekly.md"),
                            "reports/cashflow/monthly", Markdown("reports/cashflow/monthly.md"),
                            "reports/cashflow/yearly", Markdown("reports/cashflow/yearly.md")
            })
            ```
        """
        if isinstance(pages, dict):
            for k, v in pages.items():
                if k == "/":
                    k = Gui.__root_page_name
                self.add_page(name=k, page=v)
        elif isinstance(folder_name := pages, str):
            if not hasattr(self, "_root_dir"):
                self._root_dir = os.path.dirname(inspect.getabsfile(self.__frame))
            folder_path = folder_name if os.path.isabs(folder_name) else os.path.join(self._root_dir, folder_name)
            folder_name = os.path.basename(folder_path)
            if not os.path.isdir(folder_path):  # pragma: no cover
                raise RuntimeError(f"Path {folder_path} is not a valid directory")
            if folder_name in self.__directory_name_of_pages:  # pragma: no cover
                raise Exception(f"Base directory name {folder_name} of path {folder_path} is not unique")
            if folder_name in Gui.__reserved_routes:  # pragma: no cover
                raise Exception(f"Invalid directory. Directory {folder_name} is a reserved route")
            self.__directory_name_of_pages.append(folder_name)
            self.__add_pages_in_folder(folder_name, folder_path)

    # partials

    def add_partial(
        self,
        page: t.Union[str, Page],
    ) -> Partial:
        """Create a new `Partial^`.

        The [User Manual section on Partials](../../gui/pages/#partials) gives details on
        when and how to use this class.

        Arguments:
            page (Union[str, Page^]): The page to create a new Partial from.<br/>
                It can be an instance of `Markdown^` or `Html^`.<br/>
                If *page* is a string, then:

                - If *page* is set to the pathname of a readable file, the content of
                  the new `Partial` is read as Markdown input text.
                - If it is not, the content of the new `Partial` is read from this string
                  as Markdown text.

        Returns:
            The new `Partial` object defined by *page*.
        """
        new_partial = Partial()
        # Validate name
        if (
            new_partial._route in self._config.partial_routes or new_partial._route in self._config.routes
        ):  # pragma: no cover
            _warn(f'Partial name "{new_partial._route}" is already defined.')
        if isinstance(page, str):
            from .renderers import Markdown

            page = Markdown(page, frame=None)
        elif not isinstance(page, Page):  # pragma: no cover
            raise Exception(f'Partial name "{new_partial._route}" has an invalid Page.')
        new_partial._renderer = page
        # Append partial to _config
        self._config.partials.append(new_partial)
        self._config.partial_routes.append(str(new_partial._route))
        # Update locals context
        self.__locals_context.add(page._get_module_name(), page._get_locals())
        # Update variable directory
        self.__var_dir.add_frame(page._frame)
        return new_partial

    def _update_partial(self, partial: Partial):
        partials = _getscopeattr(self, Partial._PARTIALS, {})
        partials[partial._route] = partial
        _setscopeattr(self, Partial._PARTIALS, partials)
        self.__send_ws_partial(str(partial._route))

    def _get_partial(self, route: str) -> t.Optional[Partial]:
        partials = _getscopeattr(self, Partial._PARTIALS, {})
        partial = partials.get(route)
        if partial is None:
            partial = next((p for p in self._config.partials if p._route == route), None)
        return partial

    # Main binding method (bind in markdown declaration)
    def _bind_var(self, var_name: str) -> str:
        bind_context = None
        if var_name in self._get_locals_bind().keys():
            bind_context = self._get_locals_context()
        if bind_context is None:
            encoded_var_name = self.__var_dir.add_var(var_name, self._get_locals_context(), var_name)
        else:
            encoded_var_name = self.__var_dir.add_var(var_name, bind_context)
        if not hasattr(self._bindings(), encoded_var_name):
            bind_locals = self._get_locals_bind_from_context(bind_context)
            if var_name in bind_locals.keys():
                self._bind(encoded_var_name, bind_locals[var_name])
            else:
                _warn(
                    f"Variable '{var_name}' is not available in either the '{self._get_locals_context()}' or '__main__' modules."
                )
        return encoded_var_name

    def _bind_var_val(self, var_name: str, value: t.Any) -> bool:
        if _MODULE_ID not in var_name:
            var_name = self.__var_dir.add_var(var_name, self._get_locals_context())
        if not hasattr(self._bindings(), var_name):
            self._bind(var_name, value)
            return True
        return False

    def __bind_local_func(self, name: str):
        func = getattr(self, name, None)
        if func is not None and not callable(func):  # pragma: no cover
            _warn(f"{self.__class__.__name__}.{name}: {func} should be a function; looking for {name} in the script.")
            func = None
        if func is None:
            func = self._get_locals_bind().get(name)
        if func is not None:
            if callable(func):
                setattr(self, name, func)
            else:  # pragma: no cover
                _warn(f"{name}: {func} should be a function.")

    def load_config(self, config: Config) -> None:
        self._config._load(config)

    def broadcast(self, name: str, value: t.Any):
        """
        Send a new value for a variable to all connected clients.

        Arguments:
            name: The name of the variable to update or create.
            value: The value (must be serializable to json format)
        """
        self.__send_ws_broadcast(name, value)

    def _download(self, content: t.Any, name: t.Optional[str] = "", on_action: t.Optional[str] = ""):
        content_str = self._get_content("Gui.download", content, False)
        self.__send_ws_download(content_str, str(name), str(on_action))

    def _notify(
        self,
        notification_type: str = "I",
        message: str = "",
        system_notification: t.Optional[bool] = None,
        duration: t.Optional[int] = None,
    ):
        self.__send_ws_alert(
            notification_type,
            message,
            self._get_config("system_notification", False) if system_notification is None else system_notification,
            self._get_config("notification_duration", 3000) if duration is None else duration,
        )

    def _hold_actions(
        self,
        callback: t.Optional[t.Union[str, t.Callable]] = None,
        message: t.Optional[str] = "Work in Progress...",
    ):  # pragma: no cover
        action_name = callback.__name__ if callable(callback) else callback
        func = self.__get_on_cancel_block_ui(action_name)
        def_action_name = func.__name__
        _setscopeattr(self, def_action_name, func)

        if _hasscopeattr(self, Gui.__UI_BLOCK_NAME):
            _setscopeattr(self, Gui.__UI_BLOCK_NAME, True)
        else:
            self._bind(Gui.__UI_BLOCK_NAME, True)
        self.__send_ws_block(action=def_action_name, message=message, cancel=bool(action_name))

    def _resume_actions(self):  # pragma: no cover
        if _hasscopeattr(self, Gui.__UI_BLOCK_NAME):
            _setscopeattr(self, Gui.__UI_BLOCK_NAME, False)
        self.__send_ws_block(close=True)

    def _navigate(self, to: t.Optional[str] = "", tab: t.Optional[str] = None, force: t.Optional[bool] = False):
        to = to or Gui.__root_page_name
        if not to.startswith("/") and to not in self._config.routes and not urlparse(to).netloc:
            _warn(f'Cannot navigate to "{to if to != Gui.__root_page_name else "/"}": unknown page.')
            return False
        self.__send_ws_navigate(to if to != Gui.__root_page_name else "/", tab, force or False)
        return True

    def __init_route(self):
        self.__set_client_id_in_context()
        if hasattr(self, "on_init") and callable(self.on_init) and not _hasscopeattr(self, Gui.__ON_INIT_NAME):
            _setscopeattr(self, Gui.__ON_INIT_NAME, True)
            try:
                self._call_function_with_state(self.on_init, [])
            except Exception as e:  # pragma: no cover
                if not self._call_on_exception("on_init", e):
                    _warn(f"Exception raised in on_init():\n{e}")
        for name, libs in self.__extensions.items():
            for lib in libs:
                if not isinstance(lib, ElementLibrary):
                    continue
                try:
                    self._call_function_with_state(lib.on_user_init, [])
                except Exception as e:  # pragma: no cover
                    if not self._call_on_exception(f"{name}.on_user_init", e):
                        _warn(f"Exception raised in {name}.on_user_init():\n{e}")
        return self._render_route()

    def _call_on_exception(self, function_name: str, exception: Exception) -> bool:
        if hasattr(self, "on_exception") and callable(self.on_exception):
            try:
                self.on_exception(self.__get_state(), str(function_name), exception)
            except Exception as e:  # pragma: no cover
                _warn(f"Exception raised in on_exception():\n{e}")
            return True
        return False

    def __call_on_status(self) -> t.Optional[str]:
        if hasattr(self, "on_status") and callable(self.on_status):
            try:
                return self.on_status(self.__get_state())
            except Exception as e:  # pragma: no cover
                if not self._call_on_exception("on_status", e):
                    _warn(f"Exception raised in on_status:\n{e}")
        return None

    def __render_page(self, page_name: str) -> t.Any:
        self.__set_client_id_in_context()
        nav_page = page_name
        if hasattr(self, "on_navigate") and callable(self.on_navigate):
            try:
                nav_page = self.on_navigate(self.__get_state(), page_name)
                if nav_page != page_name:
                    if isinstance(nav_page, str):
                        if self._navigate(nav_page):
                            return ("Root page cannot be re-routed by on_navigate().", 302)
                    else:
                        _warn(f"on_navigate() returned an invalid page name '{nav_page}'.")
                    nav_page = page_name
            except Exception as e:  # pragma: no cover
                if not self._call_on_exception("on_navigate", e):
                    _warn(f"Exception raised in on_navigate():\n{e}")
        page = next((page_i for page_i in self._config.pages if page_i._route == nav_page), None)

        # try partials
        if page is None:
            page = self._get_partial(nav_page)
        # Make sure that there is a page instance found
        if page is None:
            return (
                jsonify({"error": f"Page '{nav_page}' doesn't exist."}),
                400,
                {"Content-Type": "application/json; charset=utf-8"},
            )
        context = page.render(self)
        if (
            nav_page == Gui.__root_page_name
            and page._rendered_jsx is not None
            and "<PageContent" not in page._rendered_jsx
        ):
            page._rendered_jsx += "<PageContent />"
        # Return jsx page
        if page._rendered_jsx is not None:
            return self._server._render(
                page._rendered_jsx, page._style if page._style is not None else "", page._head, context
            )
        else:
            return ("No page template", 404)

    def _render_route(self) -> t.Any:
        return self._server._direct_render_json(
            {
                "locations": {
                    "/" if route == Gui.__root_page_name else f"/{route}": f"/{route}" for route in self._config.routes
                },
                "blockUI": self._is_ui_blocked(),
            }
        )

    def _register_data_accessor(self, data_accessor_class: t.Type[_DataAccessor]) -> None:
        self._accessors._register(data_accessor_class)

    def get_flask_app(self) -> Flask:
        """Get the internal Flask application.

        Returns:
            The Flask instance used.
        """
        return self._server.get_flask()

    def _set_frame(self, frame: FrameType):
        if not isinstance(frame, FrameType):  # pragma: no cover
            raise RuntimeError("frame must be a FrameType where Gui can collect the local variables.")
        self.__frame = frame
        self.__default_module_name = _get_module_name_from_frame(self.__frame)

    def _set_state(self, state: State):
        if isinstance(state, State):
            self.__state = state

    def __get_client_config(self) -> t.Dict[str, t.Any]:
        config = {
            "timeZone": self._config.get_time_zone(),
            "darkMode": self._get_config("dark_mode", True),
            "baseURL": self._config._get_config("base_url", "/"),
        }
        if themes := self._get_themes():
            config["themes"] = themes
        if len(self.__extensions):
            config["extensions"] = {}
            for libs in self.__extensions.values():
                for lib in libs:
                    config["extensions"][f"./{Gui._EXTENSION_ROOT}/{lib.get_js_module_name()}"] = [  # type: ignore
                        e._get_js_name(n)
                        for n, e in lib.get_elements().items()
                        if isinstance(e, Element) and not e._is_server_only()
                    ]
        if stylekit := self._get_config("stylekit", _default_stylekit):
            config["stylekit"] = {_to_camel_case(k): v for k, v in stylekit.items()}
        return config

    def __get_css_vars(self) -> str:
        css_vars = []
        if stylekit := self._get_config("stylekit", _default_stylekit):
            for k, v in stylekit.items():
                css_vars.append(f'--{k.replace("_", "-")}:{_get_css_var_value(v)};')
        return " ".join(css_vars)

    def __init_server(self):
        app_config = self._config.config
        # Init server if there is no server
        if not hasattr(self, "_server"):
            self._server = _Server(
                self,
                path_mapping=self._path_mapping,
                flask=self._flask,
                async_mode=app_config["async_mode"],
                allow_upgrades=not app_config["notebook_proxy"],
                server_config=app_config.get("server_config"),
            )

        # Stop and reinitialize the server if it is still running as a thread
        if (_is_in_notebook() or app_config["run_in_thread"]) and hasattr(self._server, "_thread"):
            self.stop()
            self._flask_blueprint = []
            self._server = _Server(
                self,
                path_mapping=self._path_mapping,
                flask=self._flask,
                async_mode=app_config["async_mode"],
                allow_upgrades=not app_config["notebook_proxy"],
                server_config=app_config.get("server_config"),
            )
            self._bindings()._new_scopes()

    def __init_ngrok(self):
        app_config = self._config.config
        if app_config["run_server"] and app_config["ngrok_token"]:  # pragma: no cover
            if not util.find_spec("pyngrok"):
                raise RuntimeError("Cannot use ngrok as pyngrok package is not installed.")
            ngrok.set_auth_token(app_config["ngrok_token"])
            http_tunnel = ngrok.connect(app_config["port"], "http")
            _TaipyLogger._get_logger().info(f" * NGROK Public Url: {http_tunnel.public_url}")

    def __bind_default_function(self):
        with self.get_flask_app().app_context():
            self.__var_dir.process_imported_var()
            # bind on_* function if available
            self.__bind_local_func("on_init")
            self.__bind_local_func("on_change")
            self.__bind_local_func("on_action")
            self.__bind_local_func("on_navigate")
            self.__bind_local_func("on_exception")
            self.__bind_local_func("on_status")
            self.__bind_local_func("on_user_content")

    def __register_blueprint(self):
        # add en empty main page if it is not defined
        if Gui.__root_page_name not in self._config.routes:
            new_page = _Page()
            new_page._route = Gui.__root_page_name
            new_page._renderer = _EmptyPage()
            self._config.pages.append(new_page)
            self._config.routes.append(Gui.__root_page_name)

        pages_bp = Blueprint("taipy_pages", __name__)
        self._flask_blueprint.append(pages_bp)

        # server URL Rule for taipy images
        images_bp = Blueprint("taipy_images", __name__)
        images_bp.add_url_rule(f"/{Gui.__CONTENT_ROOT}/<path:path>", view_func=self.__serve_content)
        self._flask_blueprint.append(images_bp)

        # server URL for uploaded files
        upload_bp = Blueprint("taipy_upload", __name__)
        upload_bp.add_url_rule(f"/{Gui.__UPLOAD_URL}", view_func=self.__upload_files, methods=["POST"])
        self._flask_blueprint.append(upload_bp)

        # server URL for user content
        user_content_bp = Blueprint("taipy_user_content", __name__)
        user_content_bp.add_url_rule(f"/{Gui.__USER_CONTENT_URL}/<path:path>", view_func=self.__serve_user_content)
        self._flask_blueprint.append(user_content_bp)

        # server URL for extension resources
        extension_bp = Blueprint("taipy_extensions", __name__)
        extension_bp.add_url_rule(f"/{Gui._EXTENSION_ROOT}/<path:path>", view_func=self.__serve_extension)
        scripts = [
            s if bool(urlparse(s).netloc) else f"/{Gui._EXTENSION_ROOT}/{name}/{s}{lib.get_query(s)}"
            for name, libs in Gui.__extensions.items()
            for lib in libs
            for s in (lib.get_scripts() or [])
        ]
        styles = [
            s if bool(urlparse(s).netloc) else f"/{Gui._EXTENSION_ROOT}/{name}/{s}{lib.get_query(s)}"
            for name, libs in Gui.__extensions.items()
            for lib in libs
            for s in (lib.get_styles() or [])
        ]
        if self._get_config("stylekit", True):
            styles.append("stylekit/stylekit.css")
        else:
            styles.append("https://fonts.googleapis.com/css?family=Roboto:300,400,500,700&display=swap")
        if self.__css_file:
            styles.append(f"/{self.__css_file}")

        self._flask_blueprint.append(extension_bp)

        _conf_webapp_path = (
            pathlib.Path(self._get_config("webapp_path", None)) if self._get_config("webapp_path", None) else None
        )
        _webapp_path = str((pathlib.Path(__file__).parent / "webapp").resolve())
        if _conf_webapp_path:
            if _conf_webapp_path.is_dir():
                _webapp_path = str(_conf_webapp_path.resolve())
                _warn(f"Using webapp_path: '{_conf_webapp_path}'.")
            else:  # pragma: no cover
                _warn(
                    f"webapp_path: '{_conf_webapp_path}' is not a valid directory path. Falling back to '{_webapp_path}'."
                )

        self._flask_blueprint.append(
            self._server._get_default_blueprint(
                static_folder=_webapp_path,
                template_folder=_webapp_path,
                title=self._get_config("title", "Taipy App"),
                favicon=self._get_config("favicon", "favicon.png"),
                root_margin=self._get_config("margin", None),
                scripts=scripts,
                styles=styles,
                version=self.__get_version(),
                client_config=self.__get_client_config(),
                watermark=self._get_config("watermark", None),
                css_vars=self.__get_css_vars(),
                base_url=self._get_config("base_url", "/"),
            )
        )

        # Run parse markdown to force variables binding at runtime
        pages_bp.add_url_rule(f"/{Gui.__JSX_URL}/<path:page_name>", view_func=self.__render_page)

        # server URL Rule for flask rendered react-router
        pages_bp.add_url_rule(f"/{Gui.__INIT_URL}", view_func=self.__init_route)

        # Register Flask Blueprint if available
        for bp in self._flask_blueprint:
            self._server.get_flask().register_blueprint(bp)

    def run(
        self,
        run_server: bool = True,
        run_in_thread: bool = False,
        async_mode: str = "gevent",
        **kwargs,
    ) -> t.Optional[Flask]:
        """
        Starts the server that delivers pages to Web clients.

        Once you enter `run()`, users can run Web browsers and point to the Web server
        URL that `Gui` serves. The default is to listen to the _localhost_ address
        (127.0.0.1) on the port number 5000. However, the configuration of this `Gui`
        object may impact that (see the
        [Configuration](../gui/configuration.md#configuring-the-gui-instance)
        section of the User Manual for details).

        Arguments:
            run_server (bool): Whether or not to run a Web server locally.
                If set to _False_, a Web server is _not_ created and started.
            run_in_thread (bool): Whether or not to run a Web server in a separated thread.
                If set to _True_, the Web server is run is a separated thread.
                Note that if you are running in an IPython notebook context, the Web
                server is always run in a separate thread.
            async_mode (str): The asynchronous model to use for the Flask-SocketIO.
                Valid values are:<br/>

                - "gevent": Use a [gevent](https://www.gevent.org/servers.html) server.
                - "threading": Use the Flask Development Server. This allows the application to use
                  the Flask reloader (the *use_reloader* option) and Debug mode (the *debug* option).
                - "eventlet": Use an [*eventlet*](https://flask.palletsprojects.com/en/2.2.x/deploying/eventlet/)
                  event-driven WSGI server.

                The default value is "gevent"<br/>
                Note that only the "threading" value provides support for the development reloader
                functionality (*use_reloader* option). Any other value makes the *use_reloader* configuration parameter
                ignored.<br/>
                Also note that setting the *debug* argument to True forces *async_mode* to "threading".
            **kwargs (dict[str, any]): Additional keyword arguments that configure how this `Gui` is run.
                Please refer to the
                [Configuration section](../gui/configuration.md#configuring-the-gui-instance)
                of the User Manual for more information.

        Returns:
            The Flask instance if *run_server* is False else None.
        """
        # --------------------------------------------------------------------------------
        # The ssl_context argument was removed just after 1.1. It was defined as:
        # t.Optional[t.Union[ssl.SSLContext, t.Tuple[str, t.Optional[str]], t.Literal["adhoc"]]] = None
        #
        # With the doc:
        #     ssl_context (Optional[Union[ssl.SSLContext, Tuple[str, Optional[str]], te.Literal['adhoc']]]):
        #         Configures TLS to serve over HTTPS. This value can be:
        #
        #         - An `ssl.SSLContext` object
        #         - A `(cert_file, key_file)` tuple to create a typical context
        #         - The string "adhoc" to generate a temporary self-signed certificate.
        #
        #         The default value is None.
        # --------------------------------------------------------------------------------
        app_config = self._config.config

        run_root_dir = os.path.dirname(inspect.getabsfile(self.__frame))

        # Register _root_dir for abs path
        if not hasattr(self, "_root_dir"):
            self._root_dir = run_root_dir

        self.__run_kwargs = kwargs = {
            **kwargs,
            "run_server": run_server,
            "run_in_thread": run_in_thread,
            "async_mode": async_mode,
        }

        # Load application config from multiple sources (env files, kwargs, command line)
        self._config._build_config(run_root_dir, self.__env_filename, kwargs)

        self._config.resolve()

        self.__init_server()

        self.__init_ngrok()

        locals_bind = _filter_locals(self.__frame.f_locals)

        self.__locals_context.set_default(locals_bind, self.__default_module_name)

        self.__var_dir.set_default(self.__frame)

        if self.__state is None:
            self.__state = State(self, self.__locals_context.get_all_keys(), self.__locals_context.get_all_context())

        if _is_in_notebook():
            # to allow gui.state.x in notebook mode
            self.state = self.__state

        self.__bind_default_function()

        # base global ctx is TaipyHolder classes + script modules and callables
        glob_ctx: t.Dict[str, t.Any] = {t.__name__: t for t in _TaipyBase.__subclasses__()}
        glob_ctx.update({k: v for k, v in locals_bind.items() if inspect.ismodule(v) or callable(v)})
        glob_ctx[Gui.__SELF_VAR] = self

        # call on_init on each library
        for name, libs in self.__extensions.items():
            for lib in libs:
                if not isinstance(lib, ElementLibrary):
                    continue
                try:
                    lib_context = lib.on_init(self)
                    if (
                        isinstance(lib_context, tuple)
                        and len(lib_context) > 1
                        and isinstance(lib_context[0], str)
                        and lib_context[0].isidentifier()
                    ):
                        if lib_context[0] in glob_ctx:
                            _warn(f"Method {name}.on_init() returned a name already defined '{lib_context[0]}'.")
                        else:
                            glob_ctx[lib_context[0]] = lib_context[1]
                    elif lib_context:
                        _warn(
                            f"Method {name}.on_init() should return a Tuple[str, Any] where the first element must be a valid Python identifier."
                        )
                except Exception as e:  # pragma: no cover
                    if not self._call_on_exception(f"{name}.on_init", e):
                        _warn(f"Method {name}.on_init() raised an exception:\n{e}")

        # Initiate the Evaluator with the right context
        self.__evaluator = _Evaluator(glob_ctx)

        self.__register_blueprint()

        # Register data accessor communicaiton data format (JSON, Apache Arrow)
        self._accessors._set_data_format(_DataFormat.APACHE_ARROW if app_config["use_arrow"] else _DataFormat.JSON)

        # Use multi user or not
        self._bindings()._set_single_client(bool(app_config["single_client"]))

        # Start Flask Server
        if not run_server:
            return self.get_flask_app()

        return self._server.run(
            host=app_config["host"],
            port=app_config["port"],
            debug=app_config["debug"],
            use_reloader=app_config["use_reloader"],
            flask_log=app_config["flask_log"],
            run_in_thread=app_config["run_in_thread"],
            allow_unsafe_werkzeug=app_config["allow_unsafe_werkzeug"],
            notebook_proxy=app_config["notebook_proxy"],
        )

    def reload(self):  # pragma: no cover
        """
        Reload the Web server.

        This function reloads the underlying Web server only in the situation where
        it was run in a separated thread: the _run_in_thread_ parameter to the
        `(Gui.)run^` method was set to True, or you are running in an IPython notebook
        context.
        """
        if hasattr(self, "_server") and hasattr(self._server, "_thread") and self._server._is_running:
            self._server.stop_thread()
            self.run(**self.__run_kwargs)
            _TaipyLogger._get_logger().info("Gui server has been reloaded.")

    def stop(self):
        """
        Stop the Web server.

        This function stops the underlying Web server only in the situation where
        it was run in a separated thread: the _run_in_thread_ parameter to the
        `(Gui.)run^` method was set to True, or you are running in an IPython notebook
        context.
        """
        if hasattr(self, "_server") and hasattr(self._server, "_thread") and self._server._is_running:
            self._server.stop_thread()
            _TaipyLogger._get_logger().info("Gui server has been stopped.")
