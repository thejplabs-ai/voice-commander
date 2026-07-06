"""
Tests for voice/hotkeys_win32.py — parser table, lifecycle (mocked ctypes) and dispatch.

Strategy:
- Parser tests are pure (no mocks) — parse_hotkey() has no Win32 dependency.
- Lifecycle tests monkeypatch voice.hotkeys_win32.user32/kernel32 with MagicMock
  and call the internal testable units (_register_bindings, _unregister_all,
  _register_all) directly — no real pump thread is started.
- Dispatch tests patch voice.hotkeys_win32.threading.Thread and call
  _dispatch_hotkey() directly.
"""
from unittest.mock import MagicMock

import pytest

from voice import hotkeys_win32 as hk


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Isolate tests from the module-level _registered singleton dict."""
    hk._registered.clear()
    yield
    hk._registered.clear()


# ---------------------------------------------------------------------------
# parse_hotkey — pure function, tabela de casos
# ---------------------------------------------------------------------------

class TestParseHotkeyValidCombos:

    @pytest.mark.parametrize("combo,expected", [
        ("ctrl+shift+space", (hk.MOD_CONTROL | hk.MOD_SHIFT | hk.MOD_NOREPEAT, 0x20)),
        ("ctrl+shift+tab", (hk.MOD_CONTROL | hk.MOD_SHIFT | hk.MOD_NOREPEAT, 0x09)),
        ("ctrl+shift+h", (hk.MOD_CONTROL | hk.MOD_SHIFT | hk.MOD_NOREPEAT, ord("H"))),
        ("ctrl+alt+space", (hk.MOD_CONTROL | hk.MOD_ALT | hk.MOD_NOREPEAT, 0x20)),
        ("ctrl+alt+m", (hk.MOD_CONTROL | hk.MOD_ALT | hk.MOD_NOREPEAT, ord("M"))),
        ("ctrl+alt+h", (hk.MOD_CONTROL | hk.MOD_ALT | hk.MOD_NOREPEAT, ord("H"))),
    ])
    def test_combos_default_do_app(self, combo, expected):
        """The 4 current defaults plus 2 legacy combos all parse to the exact expected (mods, vk)."""
        assert hk.parse_hotkey(combo) == expected

    def test_case_insensitive_e_espacos(self):
        """' Ctrl + Shift + Space ' parses identically to 'ctrl+shift+space'."""
        assert hk.parse_hotkey(" Ctrl + Shift + Space ") == hk.parse_hotkey("ctrl+shift+space")

    def test_modifier_win(self):
        mods, vk = hk.parse_hotkey("win+space")
        assert mods == (hk.MOD_WIN | hk.MOD_NOREPEAT)
        assert vk == 0x20

    def test_modifier_windows_alias(self):
        assert hk.parse_hotkey("windows+space") == hk.parse_hotkey("win+space")

    @pytest.mark.parametrize("n", [1, 2, 12, 24])
    def test_f_keys(self, n):
        mods, vk = hk.parse_hotkey(f"ctrl+f{n}")
        assert vk == 0x70 + (n - 1)
        assert mods == (hk.MOD_CONTROL | hk.MOD_NOREPEAT)

    @pytest.mark.parametrize("key,expected_vk", [
        ("0", ord("0")), ("9", ord("9")),
        ("a", ord("A")), ("z", ord("Z")),
        ("enter", 0x0D), ("return", 0x0D),
        ("esc", 0x1B), ("escape", 0x1B),
        ("backspace", 0x08),
        ("delete", 0x2E), ("del", 0x2E),
        ("insert", 0x2D),
        ("home", 0x24), ("end", 0x23),
        ("pageup", 0x21), ("pagedown", 0x22),
        ("up", 0x26), ("down", 0x28), ("left", 0x25), ("right", 0x27),
    ])
    def test_todas_as_keys_suportadas(self, key, expected_vk):
        _, vk = hk.parse_hotkey(f"ctrl+{key}")
        assert vk == expected_vk


class TestParseHotkeyInvalidCombos:

    @pytest.mark.parametrize("combo", [
        "",
        "   ",
        "ctrl+shift",       # só modifiers, sem tecla final
        "ctrl+foo",         # tecla desconhecida
        "ctrl+a+b",         # dois non-modifiers
        "space",            # sem modifier
        "a",                # sem modifier
        "f1",               # sem modifier
    ])
    def test_combos_invalidos_levantam_value_error(self, combo):
        with pytest.raises(ValueError):
            hk.parse_hotkey(combo)

    def test_mensagem_de_erro_combo_sem_modificador(self):
        with pytest.raises(ValueError, match="modificador"):
            hk.parse_hotkey("space")


# ---------------------------------------------------------------------------
# Lifecycle — _register_bindings / _unregister_all (ctypes mockado, sem pump real)
# ---------------------------------------------------------------------------

class TestRegisterBindings:

    def test_registro_ok_sem_falhas_ids_distintos(self, monkeypatch):
        """N RegisterHotKey calls com ids distintos; failure_reporter (via _register_all) não seria chamado."""
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = 1  # sucesso
        monkeypatch.setattr(hk, "user32", mock_user32)

        bindings = [
            ("RECORD_HOTKEY", "ctrl+shift+space", MagicMock()),
            ("CYCLE_HOTKEY", "ctrl+shift+tab", MagicMock()),
            ("HISTORY_HOTKEY", "ctrl+shift+h", MagicMock()),
        ]

        failures = hk._register_bindings(bindings)

        assert failures == []
        assert mock_user32.RegisterHotKey.call_count == 3
        ids_used = [call.args[1] for call in mock_user32.RegisterHotKey.call_args_list]
        assert len(set(ids_used)) == 3
        assert len(hk._registered) == 3

    def test_registro_falhou_reporta_1409_e_continua_ciclo(self, monkeypatch):
        """RegisterHotKey retorna 0, GetLastError 1409 -> failure (key, combo, 1409); demais combos ainda registram."""
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()
        mock_user32.RegisterHotKey.side_effect = [0, 1]  # primeiro falha, segundo ok
        mock_kernel32.GetLastError.return_value = 1409  # ERROR_HOTKEY_ALREADY_REGISTERED
        monkeypatch.setattr(hk, "user32", mock_user32)
        monkeypatch.setattr(hk, "kernel32", mock_kernel32)

        bindings = [
            ("RECORD_HOTKEY", "ctrl+shift+space", MagicMock()),
            ("CYCLE_HOTKEY", "ctrl+shift+tab", MagicMock()),
        ]

        failures = hk._register_bindings(bindings)

        assert failures == [("RECORD_HOTKEY", "ctrl+shift+space", 1409)]
        assert len(hk._registered) == 1  # o segundo (que deu ok) foi registrado

    def test_combo_invalido_do_provider_vira_failure_code_zero_sem_derrubar_ciclo(self, monkeypatch):
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = 1
        monkeypatch.setattr(hk, "user32", mock_user32)

        bindings = [
            ("BAD_HOTKEY", "ctrl+foo", MagicMock()),
            ("CYCLE_HOTKEY", "ctrl+shift+tab", MagicMock()),
        ]

        failures = hk._register_bindings(bindings)

        assert failures == [("BAD_HOTKEY", "ctrl+foo", 0)]
        assert len(hk._registered) == 1  # o válido ainda registrou


class TestUnregisterAll:

    def test_unregister_chama_para_cada_id_registrado(self, monkeypatch):
        mock_user32 = MagicMock()
        monkeypatch.setattr(hk, "user32", mock_user32)
        hk._registered[1] = MagicMock()
        hk._registered[2] = MagicMock()

        hk._unregister_all()

        assert mock_user32.UnregisterHotKey.call_count == 2
        called_ids = sorted(call.args[1] for call in mock_user32.UnregisterHotKey.call_args_list)
        assert called_ids == [1, 2]
        assert hk._registered == {}

    def test_unregister_so_para_os_que_registraram(self, monkeypatch):
        """Combo que falhou o registro não deve virar chamada de UnregisterHotKey."""
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()
        mock_user32.RegisterHotKey.side_effect = [0, 1]  # primeiro falha
        mock_kernel32.GetLastError.return_value = 1409
        monkeypatch.setattr(hk, "user32", mock_user32)
        monkeypatch.setattr(hk, "kernel32", mock_kernel32)

        hk._register_bindings([
            ("A", "ctrl+shift+space", MagicMock()),
            ("B", "ctrl+shift+tab", MagicMock()),
        ])
        mock_user32.reset_mock()

        hk._unregister_all()

        mock_user32.UnregisterHotKey.assert_called_once()  # só o segundo, que registrou


class TestRegisterAllAndRebindCycle:

    def test_register_all_reporta_failures_uma_vez(self, monkeypatch):
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = 0  # tudo falha
        mock_kernel32.GetLastError.return_value = 1409
        monkeypatch.setattr(hk, "user32", mock_user32)
        monkeypatch.setattr(hk, "kernel32", mock_kernel32)

        def provider():
            return [("RECORD_HOTKEY", "ctrl+shift+space", MagicMock())]

        reported = []
        monkeypatch.setattr(hk, "_bindings_provider", provider)
        monkeypatch.setattr(hk, "_failure_reporter", lambda f: reported.append(f))

        hk._register_all()

        assert reported == [[("RECORD_HOTKEY", "ctrl+shift+space", 1409)]]

    def test_register_all_sem_falhas_nao_chama_failure_reporter(self, monkeypatch):
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = 1
        monkeypatch.setattr(hk, "user32", mock_user32)

        def provider():
            return [("RECORD_HOTKEY", "ctrl+shift+space", MagicMock())]

        reported = []
        monkeypatch.setattr(hk, "_bindings_provider", provider)
        monkeypatch.setattr(hk, "_failure_reporter", lambda f: reported.append(f))

        hk._register_all()

        assert reported == []

    def test_rebind_desregistra_antigos_e_registra_novos_do_provider(self, monkeypatch):
        """Ciclo completo de rebind: unregister all -> bindings_provider() re-lido -> register."""
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = 1
        monkeypatch.setattr(hk, "user32", mock_user32)

        provider_calls = []

        def provider():
            provider_calls.append(1)
            return [("RECORD_HOTKEY", "ctrl+shift+space", MagicMock())]

        monkeypatch.setattr(hk, "_bindings_provider", provider)
        monkeypatch.setattr(hk, "_failure_reporter", lambda f: None)

        hk._register_all()
        assert len(hk._registered) == 1
        assert len(provider_calls) == 1

        # Simula o que _pump faz ao receber WM_APP_REBIND:
        hk._unregister_all()
        hk._register_all()

        assert len(provider_calls) == 2  # provider foi re-lido
        assert mock_user32.UnregisterHotKey.call_count == 1
        assert len(hk._registered) == 1


# ---------------------------------------------------------------------------
# Dispatch — WM_HOTKEY -> worker thread (nunca inline)
# ---------------------------------------------------------------------------

class TestDispatchHotkey:

    def test_id_conhecido_spawna_thread_com_callback_certo(self, monkeypatch):
        callback = MagicMock()
        hk._registered[7] = callback

        mock_thread_cls = MagicMock()
        monkeypatch.setattr(hk.threading, "Thread", mock_thread_cls)

        hk._dispatch_hotkey(7)

        mock_thread_cls.assert_called_once_with(target=callback, daemon=True)
        mock_thread_cls.return_value.start.assert_called_once()

    def test_id_desconhecido_e_ignorado_sem_excecao(self, monkeypatch):
        mock_thread_cls = MagicMock()
        monkeypatch.setattr(hk.threading, "Thread", mock_thread_cls)

        hk._dispatch_hotkey(999)  # não deve levantar

        mock_thread_cls.assert_not_called()

    def test_dois_ids_diferentes_disparam_callbacks_diferentes(self, monkeypatch):
        callback_a = MagicMock()
        callback_b = MagicMock()
        hk._registered[1] = callback_a
        hk._registered[2] = callback_b

        mock_thread_cls = MagicMock()
        monkeypatch.setattr(hk.threading, "Thread", mock_thread_cls)

        hk._dispatch_hotkey(1)
        hk._dispatch_hotkey(2)

        targets = [call.kwargs["target"] for call in mock_thread_cls.call_args_list]
        assert targets == [callback_a, callback_b]


# ---------------------------------------------------------------------------
# _pump — resiliência a exceções (fake GetMessageW roteirizado, sem thread real)
# ---------------------------------------------------------------------------

def _scripted_get_message(script):
    """Fake GetMessageW: consome (message, wParam) do script; esgotou -> WM_QUIT (retorno 0)."""
    it = iter(script)

    def _gm(msg_ref, hwnd, lo, hi):
        try:
            message, wparam = next(it)
        except StopIteration:
            return 0
        msg_ref._obj.message = message
        msg_ref._obj.wParam = wparam
        return 1

    return _gm


class TestPumpExceptionResilience:

    def test_thread_start_raise_nao_mata_pump_e_unregister_no_exit(self, monkeypatch, capsys):
        """WM_HOTKEY cujo Thread.start levanta -> pump sobrevive, processa a mensagem
        seguinte e, no WM_QUIT, sai limpo desregistrando tudo."""
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = 1
        mock_user32.GetMessageW.side_effect = _scripted_get_message([
            (hk.WM_HOTKEY, 1),
            (hk.WM_HOTKEY, 2),
        ])
        monkeypatch.setattr(hk, "user32", mock_user32)
        monkeypatch.setattr(hk, "kernel32", MagicMock())

        def provider():
            return [
                ("A", "ctrl+shift+space", MagicMock()),
                ("B", "ctrl+shift+tab", MagicMock()),
            ]

        monkeypatch.setattr(hk, "_bindings_provider", provider)
        monkeypatch.setattr(hk, "_failure_reporter", MagicMock())

        mock_thread_cls = MagicMock()
        mock_thread_cls.return_value.start.side_effect = [RuntimeError("boom"), None]
        monkeypatch.setattr(hk.threading, "Thread", mock_thread_cls)

        hk._ready_event.clear()
        hk._pump()  # roda inline na thread do teste — não deve levantar

        assert mock_thread_cls.return_value.start.call_count == 2  # sobreviveu ao 1º raise
        assert "[ERRO]" in capsys.readouterr().out
        assert hk._registered == {}  # finally desregistrou
        assert mock_user32.UnregisterHotKey.call_count == 2

    def test_reporter_raise_no_startup_ainda_sinaliza_ready(self, monkeypatch, capsys):
        """failure_reporter levantando no registro inicial não impede _ready_event de disparar."""
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = 0  # tudo falha -> reporter é chamado
        mock_kernel32.GetLastError.return_value = 1409
        mock_user32.GetMessageW.side_effect = _scripted_get_message([])  # WM_QUIT imediato
        monkeypatch.setattr(hk, "user32", mock_user32)
        monkeypatch.setattr(hk, "kernel32", mock_kernel32)

        def provider():
            return [("A", "ctrl+shift+space", MagicMock())]

        monkeypatch.setattr(hk, "_bindings_provider", provider)
        monkeypatch.setattr(hk, "_failure_reporter", MagicMock(side_effect=RuntimeError("reporter boom")))

        hk._ready_event.clear()
        hk._pump()  # não deve levantar

        assert hk._ready_event.is_set()
        assert "[ERRO]" in capsys.readouterr().out

    def test_rebind_com_provider_quebrado_nao_mata_pump(self, monkeypatch, capsys):
        """WM_APP_REBIND cujo provider levanta -> [ERRO] + pump continua até WM_QUIT."""
        mock_user32 = MagicMock()
        mock_user32.RegisterHotKey.return_value = 1
        mock_user32.GetMessageW.side_effect = _scripted_get_message([
            (hk.WM_APP_REBIND, 0),
            (hk.WM_HOTKEY, 1),
        ])
        monkeypatch.setattr(hk, "user32", mock_user32)
        monkeypatch.setattr(hk, "kernel32", MagicMock())

        calls = {"n": 0}

        def provider():
            calls["n"] += 1
            if calls["n"] == 2:  # 1º: registro inicial ok; 2º: rebind quebra
                raise RuntimeError("provider boom")
            return [("A", "ctrl+shift+space", MagicMock())]

        monkeypatch.setattr(hk, "_bindings_provider", provider)
        monkeypatch.setattr(hk, "_failure_reporter", MagicMock())

        mock_thread_cls = MagicMock()
        monkeypatch.setattr(hk.threading, "Thread", mock_thread_cls)

        hk._ready_event.clear()
        hk._pump()

        assert "[ERRO]" in capsys.readouterr().out
        # O pump sobreviveu ao provider quebrado e continuou consumindo mensagens
        # até o WM_QUIT (3 chamadas: REBIND, HOTKEY, QUIT):
        assert mock_user32.GetMessageW.call_count == 3


# ---------------------------------------------------------------------------
# start — guard de double-start
# ---------------------------------------------------------------------------

class TestStartDoubleStartGuard:

    def test_start_no_op_se_pump_ja_vivo(self, monkeypatch):
        alive_thread = MagicMock()
        alive_thread.is_alive.return_value = True
        monkeypatch.setattr(hk, "_thread", alive_thread)

        mock_thread_cls = MagicMock()
        monkeypatch.setattr(hk.threading, "Thread", mock_thread_cls)

        hk.start(lambda: [], lambda f: None)

        mock_thread_cls.assert_not_called()


# ---------------------------------------------------------------------------
# request_rebind / stop — PostThreadMessageW falhou -> [WARN]
# ---------------------------------------------------------------------------

class TestPostThreadMessageFailureWarn:

    @staticmethod
    def _alive_thread():
        t = MagicMock()
        t.is_alive.return_value = True
        return t

    def test_request_rebind_loga_warn_se_post_falha(self, monkeypatch, capsys):
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()
        mock_user32.PostThreadMessageW.return_value = 0
        mock_kernel32.GetLastError.return_value = 5
        monkeypatch.setattr(hk, "user32", mock_user32)
        monkeypatch.setattr(hk, "kernel32", mock_kernel32)
        monkeypatch.setattr(hk, "_thread", self._alive_thread())

        hk.request_rebind()

        assert "[WARN]" in capsys.readouterr().out

    def test_stop_loga_warn_se_post_falha(self, monkeypatch, capsys):
        mock_user32 = MagicMock()
        mock_kernel32 = MagicMock()
        mock_user32.PostThreadMessageW.return_value = 0
        mock_kernel32.GetLastError.return_value = 5
        monkeypatch.setattr(hk, "user32", mock_user32)
        monkeypatch.setattr(hk, "kernel32", mock_kernel32)
        monkeypatch.setattr(hk, "_thread", self._alive_thread())

        hk.stop()

        assert "[WARN]" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# request_rebind / stop — no-op quando não iniciado
# ---------------------------------------------------------------------------

class TestNotStartedNoops:

    def test_request_rebind_no_op_se_nao_iniciado(self, monkeypatch):
        monkeypatch.setattr(hk, "_thread", None)
        mock_user32 = MagicMock()
        monkeypatch.setattr(hk, "user32", mock_user32)

        hk.request_rebind()  # não deve levantar nem postar mensagem

        mock_user32.PostThreadMessageW.assert_not_called()

    def test_stop_no_op_se_nao_iniciado(self, monkeypatch):
        monkeypatch.setattr(hk, "_thread", None)
        mock_user32 = MagicMock()
        monkeypatch.setattr(hk, "user32", mock_user32)

        hk.stop()  # idempotente, não deve levantar

        mock_user32.PostThreadMessageW.assert_not_called()
