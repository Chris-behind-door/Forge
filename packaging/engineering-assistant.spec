Name:           engineering-assistant
Version:        0.1.0
Release:        1%{?dist}
Summary:        Engineering Design Workbench - RAG + Knowledge Base + Meeting Notes

License:        MIT
BuildArch:      x86_64

%description
A Tauri desktop application for engineering design practitioners.
Features RAG-powered knowledge base, LLM chat, and meeting resolution tracking.

%install
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/usr/share/applications
mkdir -p %{buildroot}/usr/share/icons/hicolor/32x32/apps
mkdir -p %{buildroot}/usr/share/icons/hicolor/128x128/apps
mkdir -p %{buildroot}/usr/share/icons/hicolor/256x256@2/apps

install -m 755 %{_sourcedir}/engineer-assistant %{buildroot}/usr/bin/
install -m 755 %{_sourcedir}/backend %{buildroot}/usr/bin/
install -m 644 %{_sourcedir}/engineering-assistant.desktop %{buildroot}/usr/share/applications/
install -m 644 %{_sourcedir}/32x32.png %{buildroot}/usr/share/icons/hicolor/32x32/apps/engineer-assistant.png
install -m 644 %{_sourcedir}/128x128.png %{buildroot}/usr/share/icons/hicolor/128x128/apps/engineer-assistant.png
install -m 644 %{_sourcedir}/128x128@2x.png %{buildroot}/usr/share/icons/hicolor/256x256@2/apps/engineer-assistant.png

%files
/usr/bin/engineer-assistant
/usr/bin/backend
/usr/share/applications/engineering-assistant.desktop
/usr/share/icons/hicolor/32x32/apps/engineer-assistant.png
/usr/share/icons/hicolor/128x128/apps/engineer-assistant.png
/usr/share/icons/hicolor/256x256@2/apps/engineer-assistant.png
