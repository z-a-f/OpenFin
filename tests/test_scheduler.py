from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfin import scheduler
from openfin.scheduler import remove_cron_block
from openfin.storage import write_text_atomic
from tests.helpers import openfin_home, run_cli


def schedule_spec(tmp_path: Path, target: str = "cron") -> scheduler.ScheduleSpec:
    return scheduler.ScheduleSpec(
        target=target,
        send="desktop",
        morning="08:00",
        evening="18:30",
        root=tmp_path / "openfin home",
        python_executable="/usr/bin/python",
    )


def test_schedule_show_renders_cron_without_installing(tmp_path: Path) -> None:
    shown = run_cli(
        tmp_path,
        [
            "schedule",
            "show",
            "--target",
            "cron",
            "--send",
            "both",
            "--morning",
            "08:05",
            "--evening",
            "18:30",
        ],
    )

    assert shown.exit_code == 0, shown.output
    assert "OPENFIN_DIGEST_BEGIN" in shown.output
    assert "5 08 * * *" in shown.output
    assert "30 18 * * *" in shown.output
    assert "digest morning --send both" in shown.output
    assert str(openfin_home(tmp_path)) in shown.output


def test_cron_block_removal_preserves_user_entries() -> None:
    existing = "\n".join(
        [
            "0 7 * * * echo keep",
            "# OPENFIN_DIGEST_BEGIN",
            "0 9 * * * old openfin",
            "# OPENFIN_DIGEST_END",
            "0 22 * * * echo also-keep",
        ]
    )

    cleaned = remove_cron_block(existing)

    assert "echo keep" in cleaned
    assert "echo also-keep" in cleaned
    assert "old openfin" not in cleaned


def test_scheduler_target_resolution_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler.platform, "system", lambda: "Darwin")
    assert scheduler.resolve_target("auto") == "launchd"

    monkeypatch.setattr(scheduler.platform, "system", lambda: "Linux")
    monkeypatch.setattr(scheduler.shutil, "which", lambda name: "/bin/systemctl")
    assert scheduler.resolve_target("auto") == "systemd"

    monkeypatch.setattr(scheduler.shutil, "which", lambda name: None)
    assert scheduler.resolve_target("auto") == "cron"
    assert scheduler.resolve_target("cron") == "cron"
    assert scheduler.validate_time("8:05") == "08:05"

    with pytest.raises(Exception, match="time must use HH:MM"):
        scheduler.validate_time("25:00")
    with pytest.raises(Exception, match="schedule target"):
        scheduler.resolve_target("windows-task")


def test_scheduler_commands_route_to_selected_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setenv("OPENFIN_HOME", str(openfin_home(tmp_path)))
    monkeypatch.setattr(
        scheduler, "install_cron", lambda spec: calls.append(f"install {spec.target}")
    )
    monkeypatch.setattr(
        scheduler, "uninstall_cron", lambda: calls.append("uninstall cron")
    )

    scheduler.install_schedule(
        target="cron", send="desktop", morning="08:00", evening="18:00"
    )
    scheduler.uninstall_schedule(target="cron")

    assert calls == ["install cron", "uninstall cron"]


def test_scheduler_renders_systemd_and_launchd_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "systemd_user_dir", lambda: tmp_path / "systemd")
    monkeypatch.setattr(scheduler, "launch_agents_dir", lambda: tmp_path / "launchd")

    systemd = scheduler.render_schedule(schedule_spec(tmp_path, "systemd"))
    launchd = scheduler.render_schedule(schedule_spec(tmp_path, "launchd"))

    assert "openfin-digest-morning.service" in systemd
    assert "OnCalendar=*-*-* 08:00:00" in systemd
    assert "OPENFIN_HOME=" in systemd
    assert "com.openfin.digest.morning" in launchd
    assert "<integer>8</integer>" in launchd
    assert "&amp;" in scheduler.escape_xml("a&b")


def test_cron_install_and_uninstall_are_marker_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = schedule_spec(tmp_path, "cron")
    crontab_text = "0 7 * * * echo keep\n"
    writes: list[str] = []

    def fake_run(command, **kwargs):
        nonlocal crontab_text
        if command == ["/usr/bin/crontab", "-l"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=crontab_text, stderr=""
            )
        if command == ["/usr/bin/crontab", "-"]:
            crontab_text = kwargs["input"]
            writes.append(crontab_text)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(scheduler.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

    scheduler.install_cron(spec)
    scheduler.uninstall_cron()

    assert "OPENFIN_DIGEST_BEGIN" in writes[0]
    assert "echo keep" in writes[0]
    assert "OPENFIN_DIGEST_BEGIN" not in writes[1]
    assert "echo keep" in writes[1]


def test_systemd_and_launchd_install_uninstall_are_openfin_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    systemd_dir = tmp_path / "systemd"
    launchd_dir = tmp_path / "launchd"
    systemd_dir.mkdir()
    launchd_dir.mkdir()
    write_text_atomic(systemd_dir / "openfin-digest-old.timer", "old")
    write_text_atomic(launchd_dir / "com.openfin.digest.old.plist", "old")
    calls: list[list[str]] = []

    monkeypatch.setattr(scheduler, "systemd_user_dir", lambda: systemd_dir)
    monkeypatch.setattr(scheduler, "launch_agents_dir", lambda: launchd_dir)
    monkeypatch.setattr(scheduler.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda command, check=True: calls.append(command),
    )

    scheduler.install_systemd(schedule_spec(tmp_path, "systemd"))
    scheduler.uninstall_systemd()
    scheduler.install_launchd(schedule_spec(tmp_path, "launchd"))
    scheduler.uninstall_launchd()

    assert any("enable" in command for command in calls)
    assert any("disable" in command for command in calls)
    assert any("load" in command for command in calls)
    assert any("unload" in command for command in calls)
    assert not list(systemd_dir.glob("openfin-digest-*.*"))
    assert not list(launchd_dir.glob("com.openfin.digest.*.plist"))
