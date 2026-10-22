"""Minimal translation catalog for workbook rendering.

The workbook is the only translated surface: install-script log lines and
all console output stay English regardless of --language. `tr` is the
single entry point; the catalog below maps the English source strings
exactly as steps.py, workbook.py and the provision modules emit them.

Two lookup mechanisms cover the two kinds of prose:

- _EXACT: static strings, mapped 1:1 (the bulk: section titles, rationale
  paragraphs, workbook chrome);
- _PATTERNS: strings carrying interpolated values (hostnames, ports,
  URLs), matched fullmatch-style in order and re-rendered from
  templates referencing the named groups.

"en" and unknown strings pass through unchanged — fail-visible, so the
test suite asserts full coverage and a newly added untranslated string
fails loudly instead of leaking English into a rendered workbook. A new
language starts as an empty catalog: LANGUAGES gates the CLI choices,
the lookups simply fall back to English until entries land.
"""
from __future__ import annotations

import re

__all__ = ["LANGUAGES", "tr"]

LANGUAGES = ("en", "ru")


def tr(language: str, text: str) -> str:
    """Translate workbook prose; "en", unknown languages and unknown
    strings are returned unchanged."""
    if language == "en" or language not in LANGUAGES:
        return text
    if text in _EXACT:
        return _EXACT[text]
    for pattern, template in _PATTERNS:
        match = pattern.fullmatch(text)
        if match is not None:
            return template.format(**match.groupdict())
    return text


# ---------------------------------------------------------------------------
# ru: static strings
# ---------------------------------------------------------------------------
_EXACT: dict[str, str] = {
    # -- workbook chrome (workbook.py) --------------------------------------
    "> Everything below runs **inside the new system**. Enter it once with"
    " `arch-chroot /mnt/new-root`, then continue with the numbered sections.":
        "> Всё последующее выполняется **внутри новой системы**. Войдите в неё"
        " однократно командой `arch-chroot /mnt/new-root` и продолжайте"
        " по пронумерованным разделам.",

    "## 0. Target facts":
        "## 0. Сведения о целевой машине",
    "The blocks below were rendered for the facts listed in the"
    " header. Verify them on the target first.":
        "Приведённые ниже блоки сформированы для значений, указанных"
        " в заголовке. Проверьте их на целевой машине прежде всего.",
    "If systemd-detect-virt or discard_max_bytes disagree with the"
    " rendered values, re-render the workbook with matching"
    " `--virt` / `--discard` flags.":
        "При расхождении systemd-detect-virt либо discard_max_bytes"
        " с отображёнными значениями выполните повторное формирование"
        " руководства с соответствующими параметрами `--virt` / `--discard`.",

    # -- install steps: titles ----------------------------------------------
    "Creating filesystems and mounting":
        "Создание файловых систем и монтирование",
    "Pointing the live pacman mirrorlist at the local cache mirror":
        "Настройка mirrorlist live-среды на локальное кэширующее зеркало",
    "Bootstrapping base system with pacstrap (long step)":
        "Развёртывание базовой системы посредством pacstrap (длительный шаг)",
    "Generating /etc/fstab":
        "Генерация /etc/fstab",
    "Setting root password, enabling sshd":
        "Задание пароля root, включение sshd",
    "Reserving DRM card0 for the guest GPU (spice agent mapping)":
        "Закрепление DRM-карты card0 за GPU гостевой системы"
        " (сопоставление spice-агента)",
    "Installing GRUB bootloader":
        "Установка загрузчика GRUB",
    "Tuning /etc/pacman.conf":
        "Настройка /etc/pacman.conf",
    "Installing the package-cache prune hook":
        "Установка хука очистки кэша пакетов",
    "Fetching and signing third-party repository keys":
        "Получение и локальная подпись ключей сторонних репозиториев",
    "Granting wheel group sudo rights":
        "Предоставление группе wheel прав sudo",
    "Installing console packages (long step)":
        "Установка консольных пакетов (длительный шаг)",
    "Installing console development packages (long step)":
        "Установка консольных пакетов разработки (длительный шаг)",
    "Installing Xlibre X server (long step)":
        "Установка X-сервера Xlibre (длительный шаг)",
    "Installing Sonic DE base (long step)":
        "Установка базовой части Sonic DE (длительный шаг)",
    "Installing graphical packages (long step)":
        "Установка графических пакетов (длительный шаг)",
    "Installing graphical development packages (long step)":
        "Установка графических пакетов разработки (длительный шаг)",
    "Enabling sonic-login-manager display manager":
        "Включение экранного менеджера sonic-login-manager",
    "Making the ACPI power button shut down":
        "Настройка кнопки питания ACPI на выключение",
    "Handing ACPI power buttons to logind (VM target)":
        "Передача кнопок питания ACPI под управление logind (ВМ-цель)",
    "Disabling screen locking (VM target)":
        "Отключение блокировки экрана (ВМ-цель)",
    "Enabling the SPICE agent daemon (kvm/qemu target)":
        "Включение демона SPICE-агента (цель kvm/qemu)",
    "Disabling sshd password authentication":
        "Отключение парольной аутентификации sshd",
    "Enabling network services":
        "Включение сетевых служб",
    "Enabling weekly batch TRIM (fstrim.timer)":
        "Включение еженедельной пакетной очистки TRIM (fstrim.timer)",
    "Tuning guest memory pressure (small page cache)":
        "Настройка вытеснения памяти гостевой системы (небольшой кэш страниц)",
    "Working around the frozen VirtualBox HDA DMA position reporting":
        "Обход остановки отчётов о DMA-позиции HDA в VirtualBox",
    "Pinning the host-only network address":
        "Закрепление адреса host-only сети",
    "Installing the DNS fallback NetworkManager dispatcher":
        "Установка обработчика NetworkManager для резервного DNS",
    "Installing and enabling firewalld":
        "Установка и включение firewalld",
    "Pointing /etc/resolv.conf at systemd-resolved's stub":
        "Переключение /etc/resolv.conf на заглушку systemd-resolved",
    "Restoring DNS resolution if it is broken":
        "Восстановление разрешения имён при его неработоспособности",
    "Installing the opencode user service":
        "Установка пользовательской службы opencode",

    # -- install steps: rationales -------------------------------------------
    "A previous failed run can leave /mnt/new-root (plus its /boot ESP) mounted"
    " and its swapfile active; sfdisk refuses to repartition a busy disk. Both"
    " release commands are no-ops on a fresh system.":
        "Предыдущий неудачный запуск может оставить смонтированным"
        " /mnt/new-root (включая его ESP в /boot) и активным файл подкачки;"
        " sfdisk отказывается размечать занятый диск. Обе освобождающие"
        " команды на чистой системе не выполняют никаких действий.",

    "Releasing the target mounts and swap":
        "Освобождение точек монтирования целевого диска и файла подкачки",
    "The script exits with the installed filesystem unmounted, so the"
    " host-side poweroff (clean or forced) never races a pending write; the"
    " same commands double as the pre-install cleanup at the top.":
        "Скрипт завершает работу с размонтированной файловой системой"
        " целевого диска, поэтому выключение ВМ со стороны хоста (штатное или"
        " принудительное) не соревнуется с незавершённой записью; те же"
        " команды в начале скрипта служат предустановочной очисткой.",

    "On VM targets whose hypervisor forwards TRIM, root is mounted with the"
    " continuous 'discard' option so freed extents unmap the hypervisor-side drive"
    " image at once; genfstab copies the option into fstab. Physical SSDs get the"
    " weekly fstrim.timer batch instead (enabled below when the disk accepts"
    " discards).":
        "На ВМ-целях, гипервизор которых обеспечивает проброс TRIM, корень"
        " монтируется с непрерывной опцией «discard», поэтому освобождённые"
        " экстенты немедленно освобождают образ диска на стороне гипервизора;"
        " genfstab переносит опцию в fstab. Для физических SSD вместо этого"
        " применяется еженедельная пакетная очистка fstrim.timer (включается"
        " ниже при поддержке discard диском).",

    "Sole mirrorlist entry for the live environment: pacstrap downloads the"
    " official repos through the local arch-cache-mirror, so reinstalls hit its"
    " package cache instead of the public mirrors.":
        "Единственная запись mirrorlist для live-среды: pacstrap загружает"
        " официальные репозитории через локальный arch-cache-mirror, поэтому"
        " повторные установки обслуживаются его кэшем пакетов, а не публичными"
        " зеркалами.",

    "Base system plus a console toolbox. The VirtualBox guest-utils variant is"
    " chosen per target (the two variants conflict): the headless -nox build on"
    " console installs, the full build on graphical ones, and neither anywhere"
    " else.":
        "Базовая система и консольный арсенал. Вариант virtualbox-guest-utils"
        " выбирается по целевой машине (варианты конфликтуют между собой):"
        " сборка -nox без графической части на консольных установках, полная"
        " сборка на графических, на прочих целях — ни одна из них.",

    "UUID-based fstab for the new system.":
        "fstab новой системы с привязкой по UUID.",

    "The locale line is uncommented in /etc/locale.gen before locale-gen; the"
    " sed pattern escapes the dots in the locale name.":
        "Строка локали раскомментируется в /etc/locale.gen перед locale-gen;"
        " шаблон sed экранирует точки в имени локали.",

    "Built-in simpledrm registers DRM minor 0 at boot and is kicked off"
    " by the real GPU driver's aperture takeover afterwards, leaving the"
    " GPU as card1 with no card0. spice-vdagent enumerates cards"
    " card0..card9 but stops at the first missing index, so its"
    " server-display to X-output PCI mapping fails and the agent drops"
    " to output-index matching (single display only). Blacklisting the"
    " sysfb_init initcall stops the firmware framebuffer device from"
    " ever registering, so the GPU driver takes minor 0 = card0."
    " Must land before the grub-mkconfig in the next step.":
        "Встроенный simpledrm регистрирует DRM minor 0 при загрузке и затем"
        " вытесняется при захвате апертуры полноценным драйвером GPU,"
        " вследствие чего GPU остаётся card1 без card0. spice-vdagent"
        " перечисляет карты card0..card9, но останавливается на первом"
        " отсутствующем индексе, поэтому сопоставление экранов сервера"
        " с выходами X по PCI-адресу не выполняется и агент переходит к подбору"
        " по индексу выхода (только один дисплей). Внесение sysfb_init"
        " в список блокировки исключает регистрацию устройства"
        " firmware-фреймбуфера, вследствие чего драйвер GPU занимает"
        " minor 0 = card0. Должно выполняться до grub-mkconfig"
        " в следующем шаге.",

    "The NVRAM entry alone is unreliable: every wipe randomizes the MBR disk-id"
    " so older entries stop resolving, and VirtualBox EFI drops guest-written"
    " boot entries on guest-initiated reboots. The second, --removable install"
    " additionally provides the signature-less /EFI/BOOT/BOOTX64.EFI fallback"
    " that boots without any NVRAM entry.":
        "Одной записи в NVRAM нельзя доверять: каждая очистка диска"
        " рандомизирует идентификатор MBR, из-за чего старые записи перестают"
        " разрешаться, а EFI VirtualBox утрачивает созданные гостем загрузочные"
        " записи при перезагрузке из гостевой системы. Вторая установка"
        " с --removable дополнительно предоставляет неподписанный резервный"
        " загрузчик /EFI/BOOT/BOOTX64.EFI, способный загрузиться без"
        " какой-либо записи в NVRAM.",

    "Color, parallel downloads, an IgnorePkg set and the multilib repo, then"
    " the two third-party repositories are appended.":
        "Color, параллельная загрузка, набор IgnorePkg и репозиторий multilib,"
        " затем добавляются два сторонних репозитория.",

    "Same sole source for the installed system as for the live environment.":
        "Тот же единственный источник для установленной системы, что и для"
        " live-среды.",

    "Empties the package cache after every pacman transaction. Arch's"
    " default keeps at least one compressed copy of every installed"
    " package in /var/cache/pacman/pkg forever (plus every downloaded"
    " version until manually cleaned); here the cache never duplicates"
    " the installed set. Deleted bytes are genuinely reclaimed through"
    " the discard handling above (continuous root discard on VMs,"
    " weekly fstrim on SSDs); on --local-mirror targets re-downloads"
    " come from the host LAN mirror. The cost is offline rollback:"
    " downgrades need the package re-fetched (the Arch archives carry"
    " the official repos; the third-party repos may not keep old"
    " versions). Plain rm instead of pacman -Scc: PostTransaction hooks"
    " run while the parent transaction still holds"
    " /var/lib/pacman/db.lck, so the nested pacman would fail with"
    " 'unable to lock database' on every run, while rm needs nothing"
    " beyond coreutils (pacman-contrib is not installed). Interrupted"
    " downloads leave nothing to resume: pacman >= 6.1 stages partial"
    " downloads under temporary download-* directories inside the"
    " cache and they do not survive the transaction; the hook clears"
    " those leftovers too (only a killed pacman leaves one behind, and"
    " the next transaction's hook run prunes it).":
        "Опустошает кэш пакетов после каждой транзакции pacman. Настройка Arch"
        " по умолчанию хранит в /var/cache/pacman/pkg не менее одной сжатой"
        " копии каждого установленного пакета бессрочно (плюс все загруженные"
        " версии до ручной очистки); здесь кэш никогда не дублирует"
        " установленный набор. Удалённые байты реально возвращаются благодаря"
        " описанной выше обработке discard (непрерывный discard корня на ВМ,"
        " еженедельный fstrim на SSD); на целях с --local-mirror повторные"
        " загрузки поступают из зеркала в локальной сети хоста. Плата —"
        " автономный откат: для понижения версии пакет требуется загрузить"
        " заново (архивы Arch хранят официальные репозитории; сторонние"
        " репозитории могут не хранить старые версии). Используется обычный rm"
        " вместо pacman -Scc: хуки PostTransaction выполняются, пока"
        " родительская транзакция удерживает /var/lib/pacman/db.lck, вследствие"
        " чего вложенный pacman завершался бы ошибкой «unable to lock database»"
        " при каждом запуске, тогда как rm не требует ничего сверх coreutils"
        " (pacman-contrib не устанавливается). Прерванные загрузки не оставляют"
        " данных для возобновления: pacman >= 6.1 размещает частичные загрузки"
        " во временных каталогах download-* внутри кэша, и они не переживают"
        " транзакцию; хук очищает и эти остатки (остаются они только от"
        " принудительно завершённого pacman, и следующее выполнение хука их"
        " удаляет).",

    "The signing keys are fetched from their upstream homes (the cache mirror"
    " proxies repository files only, not key .asc files) and locally signed.":
        "Ключи подписи получаются из их исходных расположений (кэширующее"
        " зеркало проксирует только файлы репозиториев, но не .asc-файлы"
        " ключей) и подписываются локально.",

    "Fixed-size swapfile with a random clear UUID. On discard-capable disks the"
    " fstab line carries 'discard' so swapon trims unused swap blocks (a full"
    " trim at every swapon, plus frees as pages are released).":
        "Файл подкачки фиксированного размера со случайным очищенным UUID."
        " На дисках с поддержкой discard запись fstab содержит «discard»,"
        " вследствие чего swapon освобождает неиспользуемые блоки подкачки"
        " (полная очистка при каждом swapon плюс освобождение по мере выдачи"
        " страниц).",

    "The console toolbox. Sound is explicit (pipewire, wireplumber,"
    " pipewire-pulse) instead of left to transitive dependencies.":
        "Консольный арсенал. Звук задаётся явно (pipewire, wireplumber,"
        " pipewire-pulse), а не остаётся на транзитивных зависимостях.",

    "Requested with --devel: compilers and SDKs, language servers,"
    " containers, CI/CD, cloud/IaC, VM host tooling, reverse"
    " engineering and security tooling on top of the console toolbox.":
        "Запрошено параметром --devel: компиляторы и SDK, серверы языков,"
        " контейнеры, CI/CD, облачные/IaC-средства, инструментарий хоста ВМ,"
        " средства обратной разработки и безопасности поверх консольного"
        " арсенала.",

    "Installed before the sonic packages: xlibre-xserver Provides:"
    " xorg-server, and sonic-login-manager Requires: xorg-server — with the"
    " server installed first that dependency resolves to the xlibre build"
    " instead of pulling in the conflicting stock xorg-server.":
        "Устанавливается до sonic-пакетов: xlibre-xserver содержит"
        " Provides: xorg-server, а sonic-login-manager требует Requires:"
        " xorg-server — при установке сервера в первую очередь данная"
        " зависимость разрешается в сборку xlibre, а не в конфликтующий"
        " штатный xorg-server.",

    "Installed before the graphical list: the sonic packages conflict with"
    " (and provide) the stock KDE/Plasma ones, so later dependencies resolve"
    " to the sonic replacements.":
        "Устанавливается до графического списка: sonic-пакеты конфликтуют"
        " со штатными пакетами KDE/Plasma (и предоставляют их замены),"
        " поэтому последующие зависимости разрешаются в замены sonic.",

    "open-vm-tools is kept only on VMware targets; elsewhere it is dead"
    " weight.":
        "open-vm-tools сохраняется только на целях VMware; на прочих он является"
        " балластом.",

    "Requested with --devel: VM management, graphics debugging and"
    " benchmarks, 3D content creation, Vulkan development on top of"
    " the graphical set.":
        "Запрошено параметром --devel: управление ВМ, отладка графики"
        " и бенчмарки, создание 3D-контента, разработка Vulkan поверх"
        " графического набора.",

    "soniclogin refuses to autologin without a Session= entry; the session"
    " is auto-detected from the installed .desktop files. The find carries"
    " || true because the current session set is X11-only: find exits 1 on"
    " the missing wayland directory and set -e would abort before the empty"
    " check.":
        "soniclogin не выполняет автоматический вход без записи Session=;"
        " сессия определяется автоматически по установленным .desktop-файлам."
        " Команда find снабжена || true, поскольку текущий набор сессий —"
        " только X11: find завершается кодом 1 при отсутствии каталога wayland,"
        " и set -e прервал бы выполнение до проверки на пустоту.",

    "The created user gets passwordless sudo and the provided public key for"
    " initial access. Root-owned files in a user's home make sshd (StrictModes)"
    " refuse them, hence the explicit chown.":
        "Созданный пользователь получает sudo без пароля и указанный открытый"
        " ключ для первоначального доступа. Файлы, принадлежащие root,"
        " в домашнем каталоге пользователя отклоняются sshd (StrictModes),"
        " поэтому выполняется явный chown.",

    "Seeds PowerDevil's Shutdown action (8) for stacks where its button"
    " delivery works (e.g. Wayland); logind's inhibitor would otherwise leave"
    " the button on the logout-dialog default.":
        "Прописывает действие Shutdown (8) в PowerDevil для стеков, где доставка"
        " нажатий у него работает (например Wayland); иначе ингибитор logind"
        " оставил бы кнопку на значении по умолчанию с диалогом выхода.",

    "On X11 sessions PowerDevil's button delivery is dead (its"
    " kglobalaccel grabs never fire a configured action) while its logind"
    " inhibitor blocks the default poweroff: the button becomes a no-op."
    " VMs have no battery or backlight, so the daemon is masked and logind's"
    " HandlePowerKey=poweroff shuts the machine down.":
        "В сеансах X11 обработка нажатий в PowerDevil не работает (его захваты"
        " kglobalaccel никогда не вызывают настроенное действие), а его"
        " ингибитор logind блокирует стандартное выключение: кнопка становится"
        " бесполезной. У ВМ нет батареи и подсветки, поэтому демон маскируется,"
        " и HandlePowerKey=poweroff в logind выключает машину.",

    "Meta+L muscle memory aimed at the host OS locks the VM desktop"
    " instead, and autolock or lock-on-resume can freeze unattended test"
    " runs behind a password prompt. Autolock and lock-on-resume are off"
    " and the Lock Session shortcut is cleared; physical targets keep"
    " normal locking.":
        "Привычное сочетание Meta+L, адресованное ОС хоста, блокирует вместо"
        " неё рабочий стол ВМ, а автоблокировка либо блокировка при возврате"
        " из простоя способна остановить автоматические тестовые прогоны за"
        " запросом пароля. Автоблокировка и блокировка при возврате отключены,"
        " сочетание «Заблокировать сеанс» очищено; физические цели сохраняют"
        " обычную блокировку.",

    "spice-vdagentd.socket has no [Install] section, so nothing enables"
    " or starts it: the session agent then skips itself (its"
    " ConditionPathExists waits for the daemon's socket) and the guest"
    " loses clipboard sharing and console-resize resolution following."
    " add-wants creates the symlink `systemctl enable` refuses to; the"
    " daemon itself activates on the first session-agent connection."
    " Needs the domain's com.redhat.spice.0 spicevmc channel, which the"
    " provisioning adds.":
        "spice-vdagentd.socket не имеет секции [Install], поэтому ничто его не"
        " включает и не запускает: сессионный агент тогда пропускает себя (его"
        " ConditionPathExists ожидает сокет демона), и гостевая система"
        " утрачивает общий буфер обмена и подстройку разрешения под размер окна"
        " консоли. add-wants создаёт символическую ссылку, от которой"
        " отказывается `systemctl enable`; сам демон активируется при первом"
        " подключении сессионного агента. Требуется канал spicevmc"
        " com.redhat.spice.0 в домене, добавляемый при создании ВМ.",

    "Landed after the user and its authorized_keys exist, so post-reboot access"
    " is public-key only.":
        "Выполняется после создания пользователя и его authorized_keys,"
        " вследствие чего доступ после перезагрузки — только по открытому"
        " ключу.",

    "NetworkManager and systemd-resolved replace the ISO's network stack;"
    " without vboxservice the host never sends video-mode hints and"
    " VBoxClient blanks the screen on VirtualBox.":
        "NetworkManager и systemd-resolved заменяют сетевой стек ISO;"
        " без vboxservice хост никогда не передаёт подсказки о видеорежиме,"
        " и VBoxClient гасит экран на VirtualBox.",

    "Low wear and no per-delete latency on real SSDs; on VM disks it still"
    " unmaps free space (compacting the drive image) on top of the"
    " continuous root discard.":
        "Низкий износ и отсутствие задержки на каждое удаление на реальных SSD;"
        " на дисках ВМ он дополнительно освобождает свободное пространство"
        " (уплотняя образ диска) поверх непрерывного discard корня.",

    "The VM boots with its full RAM (current = max) and the virtio balloon"
    " returns pages to the host only when the guest notices pressure:"
    " freePageReporting hands back free-page hints and autodeflate inflates"
    " the balloon under host pressure. watermark_scale_factor = 500 wakes"
    " kswapd at 5% free memory (0.1% default) and the lowered"
    " vfs_cache_pressure makes reclaim target the page cache rather than"
    " the dentry/inode caches, keeping memory the hypervisor could reuse."
    " (The pagecache-limit sysctls are SUSE out-of-tree, not mainline.)":
        "ВМ загружается со всем объёмом памяти (current = max), и virtio-balloon"
        " возвращает страницы хосту только при заметном гостем давлении:"
        " freePageReporting передаёт подсказки о свободных страницах,"
        " autodeflate раздувает balloon под давлением хоста."
        " watermark_scale_factor = 500 будит kswapd при 5% свободной памяти"
        " (по умолчанию 0,1%), а пониженный vfs_cache_pressure направляет"
        " вытеснение на кэш страниц, а не на кэши dentry/inode, удерживая"
        " память, которую гипервизор мог бы использовать повторно. (Sysctl"
        " ограничения кэша страниц — внешние наработки SUSE, не основная"
        " ветка.)",

    "VirtualBox's emulated HDA advertises a DMA position buffer that never"
    " advances: the guest reads hw_ptr stuck at 0, the audio graph stalls on"
    " the first playback and the emulated controller keeps looping whatever"
    " sits in the ALSA ring buffer — a short fragment repeats indefinitely."
    " position_fix=1 reads the LPIB register instead, which the emulation"
    " keeps accurate.":
        "Эмулированная HDA в VirtualBox предоставляет DMA-буфер позиции,"
        " который никогда не продвигается: гость читает hw_ptr, застывший"
        " на 0, звуковой граф останавливается при первом же воспроизведении,"
        " а эмулированный контроллер продолжает зацикливать содержимое"
        " кольцевого буфера ALSA — короткий фрагмент повторяется бесконечно."
        " position_fix=1 читает вместо буфера регистр LPIB, который эмуляция"
        " поддерживает точным.",

    "The host-only NIC is the fast host<->guest path (SSH transport, local"
    " mirror). Its address is pinned statically, keyed by MAC: VirtualBox's"
    " host-only DHCP server matches per-MAC fixed-address configs against"
    " the DHCP client-id option, which NetworkManager sends, so a"
    " server-side binding alone is not honored. The profile hands out no"
    " gateway or DNS — both stay on the NAT NIC, keeping roaming behaviour"
    " unchanged.":
        "Host-only адаптер — быстрый канал хост↔гость (SSH-транспорт,"
        " локальное зеркало). Его адрес закреплён статически с привязкой к"
        " MAC: DHCP-сервер host-only сети VirtualBox сопоставляет конфигурации"
        " фиксированных адресов по MAC с опцией DHCP client-id, которую"
        " отправляет NetworkManager, поэтому серверная привязка сама по себе"
        " не учитывается. Профиль не выдаёт ни шлюза, ни DNS — оба остаются"
        " на NAT-адаптере, и поведение при смене сетей не меняется.",

    "Probes the connection's DHCP DNS servers on every network event and uses"
    " them only while at least one answers, so router DNS, search domains and"
    " split-DNS all apply; when none answers, DHCP DNS is ignored so"
    " systemd-resolved's fallback resolvers take over. Self-reverting on the"
    " next event after the network heals.":
        "Опрашивает DHCP-серверы DNS соединения при каждом сетевом событии и"
        " использует их, лишь пока отвечает хотя бы один, благодаря чему"
        " применяются DNS маршрутизатора, домены поиска и split-DNS; когда не"
        " отвечает ни один, DHCP DNS игнорируется и вступают резервные"
        " резолверы systemd-resolved. Самовосстанавливается при следующем"
        " событии после восстановления сети.",

    "The installed dispatcher hook does this automatically on every network"
    " event; this is the same kick, for when resolution is broken right now.":
        "Установленный обработчик dispatcher выполняет это автоматически при"
        " каждом сетевом событии; здесь — то же самое принудительное выполнение"
        " на случай, когда разрешение имён не работает прямо сейчас.",

    "First keypair for the created user (ed25519, empty passphrase); the key"
    " passed to the installer was only for initial access.":
        "Первая пара ключей созданного пользователя (ed25519, пустая парольная"
        " фраза); ключ, переданный установщику, служил только для"
        " первоначального доступа.",

    "The user manager — and with it the opencode unit — runs from boot,"
    " without an active login session.":
        "Пользовательский менеджер — а вместе с ним и юнит opencode — работает"
        " с момента загрузки, без активного сеанса входа.",

    "opencode v2 protects the server with HTTP basic auth; without"
    " OPENCODE_SERVER_PASSWORD it would generate a random password into the"
    " journal on every start. The basic-auth username is hardcoded to"
    " 'opencode' (as of 2.0.18). The start is queued with --no-block"
    " because a blocking start can hold the SSH channel open; verify with"
    " `systemctl --user is-active opencode.service`.":
        "opencode v2 защищает сервер базовой HTTP-аутентификацией; без"
        " OPENCODE_SERVER_PASSWORD при каждом запуске генерировался бы"
        " случайный пароль, попадающий в журнал. Имя пользователя basic-auth"
        " жёстко задано как «opencode» (по состоянию на 2.0.18). Запуск"
        " ставится в очередь с --no-block, поскольку блокирующий запуск способен"
        " удерживать канал SSH открытым; проверка выполняется командой"
        " `systemctl --user is-active opencode.service`.",

    # -- provision workbook prose --------------------------------------------
    "Boot the VM. At the systemd-boot menu press `e`, append"
    " ` console=ttyS0,115200` to the end of the `options` line and press"
    " `Enter` — the same edit the tool blind-types over the hypervisor"
    " keyboard. The kernel then talks on the serial line; attach a"
    " terminal to it (a newline re-shows the login prompt):":
        "Загрузите ВМ. В меню systemd-boot нажмите `e`, допишите"
        " ` console=ttyS0,115200` в конец строки `options` и нажмите `Enter` —"
        " то же самое изменение инструмент «вслепую» вводит через клавиатуру"
        " гипервизора. После этого ядро общается через последовательную линию;"
        " подключите к ней терминал (перевод строки заново показывает"
        " приглашение входа):",

    "Log in as `root` (the live ISO has no root password yet), set the"
    " root password the install's SSH transport will use, and read the"
    " guest's DHCP addresses:":
        "Войдите как `root` (в live-ISO ещё нет пароля root), задайте пароль"
        " root, который будет использовать SSH-транспорт установки, и считайте"
        " DHCP-адреса гостевой системы:",
}


# ---------------------------------------------------------------------------
# ru: strings with interpolated values (matched fullmatch, in order)
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # workbook chrome
    (re.compile(r"# archinstaller workbook — (?P<hostname>.+)"),
     "# Руководство archinstaller — {hostname}"),
    (re.compile(r"Rendered (?P<date>\S+) with: (?P<facts>.+)\."),
     "Отображено {date}. Параметры: {facts}."),
    (re.compile(r"> \*\*Caution — live credentials\.\*\* This workbook embeds"
                r" real passwords \((?P<which>[^)]*)\)\. Treat the file as a"
                r" secret: it was written with mode 0600 — do not commit,"
                r" share or paste it\. Rotate the passwords once convenient"
                r" after use\."),
     "> **Внимание — действующие учётные данные.** Настоящий файл содержит"
     " действующие пароли ({which}). Файл подлежит обращению как секретный"
     " материал: записан с правами доступа 0600 — не помещать в репозитории,"
     " не передавать, не публиковать. По завершении работы пароли следует"
     " заменить."),
    (re.compile(r"> After the install finishes, reboot, then log in over SSH"
                r" as `(?P<user>[^`]+)` \(public-key only\)\. Root-level"
                r" commands below are prefixed with `sudo` \(passwordless"
                r" for `(?P=user)`\)\."),
     "> По завершении установки выполните перезагрузку, после чего войдите"
     " по SSH под пользователем `{user}` (только по открытому ключу). Команды"
     " уровня root ниже снабжены префиксом `sudo` (без ввода пароля для"
     " `{user}`)."),

    # step titles
    (re.compile(r"Partitioning (?P<disk>.+) \(1G ESP \+ rest for root\)"),
     "Разметка диска {disk} (раздел ESP на 1 ГиБ, остальное — под корень)"),
    (re.compile(r"Setting hostname '(?P<host>[^']*)' and locale '(?P<locale>[^']*)'"),
     "Задание имени узла '{host}' и локали '{locale}'"),
    (re.compile(r"Pointing pacman at the local cache mirror \((?P<url>.+)\)"),
     "Настройка pacman на локальное кэширующее зеркало ({url})"),
    (re.compile(r"Creating (?P<size>\S+) swap file"),
     "Создание файла подкачки размером {size}"),
    (re.compile(r"Enabling sonic-login-manager autologin for (?P<user>.+)"),
     "Включение автоматического входа sonic-login-manager для {user}"),
    (re.compile(r"Creating user (?P<user>.+)"),
     "Создание пользователя {user}"),
    (re.compile(r"Granting passwordless sudo to (?P<user>.+)"),
     "Предоставление пользователю {user} sudo без пароля"),
    (re.compile(r"Setting the timezone to (?P<timezone>.+)"),
     "Установка часового пояса {timezone}"),
    (re.compile(r"Generating an SSH keypair for (?P<user>.+)"),
     "Генерация пары ключей SSH для {user}"),
    (re.compile(r"Letting (?P<user>.+)'s services run without a login session"),
     "Запуск служб пользователя {user} без активного сеанса входа"),
    (re.compile(r"Opening port (?P<port>\d+) in firewalld"),
     "Открытие порта {port} в firewalld"),

    # provision workbook prose
    (re.compile(r"Provision the VirtualBox VM '(?P<name>[^']*)' \(serial line"
                r" on TCP (?P<serial>\d+), SSH over the host-only network at"
                r" the pinned address; NAT port-forward"
                r" 127\.0\.0\.1:(?P<ssh>\d+) is the fallback\):"),
     "Создание ВМ VirtualBox '{name}' (последовательная линия на TCP {serial},"
     " SSH через host-only сеть на закреплённом адресе; проброс SSH-порта"
     " 127.0.0.1:{ssh} — резервный путь):"),
    (re.compile(r"> The VirtualBox Extension Pack is not installed on this"
                r" host; USB 3\.0 \(xHCI\) is not enabled\. After installing"
                r" it, run `vboxmanage modifyvm (?P<name>[^`]+) --usb-xhci on`"
                r" \(VM powered off\)\.\n\n"),
     "> Extension Pack для VirtualBox не установлен на данном хосте; USB 3.0"
     " (xHCI) не включён. После его установки выполните `vboxmanage modifyvm"
     " {name} --usb-xhci on` (при выключенной ВМ).\n\n"),
    (re.compile(r"Provision the libvirt domain '(?P<name>[^']*)' on"
                r" (?P<uri>\S+) \(network: (?P<network>[^,]+), serial line on"
                r" TCP (?P<serial>\d+)\):"),
     "Создание libvirt-домена '{name}' на {uri} (сеть: {network},"
     " последовательная линия на TCP {serial}):"),
    (re.compile(r"Save the domain XML as `archinstaller-provision-"
                r"(?P<name>[^`]+)\.xml`:"),
     "Сохраните XML домена в файле `archinstaller-provision-{name}.xml`:"),
    (re.compile(r"The live ISO then answers SSH at (?P<host>.+)\. The sections"
                r" below run inside that live environment — over the serial"
                r" line or in the VM window's console, whichever you prefer\."),
     "После этого live-ISO отвечает по SSH на {host}. Разделы ниже выполняются"
     " в этой live-среде — через последовательную линию либо в консоли окна"
     " ВМ, как удобнее."),
]
