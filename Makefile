# a simple makefile to pull a tar ball.

PREFIX?=/usr
DISTNAME=inkscape-cutcutgo
EXCL=--exclude \*.orig --exclude \*.pyc
ALL=README.md *.png *.sh *.rules *.py *.inx examples misc cutcutgo locale
VERS=$$(python3 ./sendto_cricut.py --version)

## echo python3 ./sendto_silhouette.py
# 'module' object has no attribute 'core'
# 'module' object has no attribute 'core'
# done. 0 min 0 sec
#
# debian 8
# --------
# echo > /etc/apt/sources.list.d/backports.list 'deb http://ftp.debian.org debian jessie-backports main'
# apt-get update
# apt-get -t jessie-backports install python3-usb
# vi /etc/group
# lp:x:debian


DEST=$(DESTDIR)$(PREFIX)/share/inkscape/extensions
LOCALE=$(DESTDIR)$(PREFIX)/share/locale
UDEV=$(DESTDIR)/lib/udev
INKSCAPE_TEMPLATES=$(DESTDIR)$(PREFIX)/share/inkscape/templates

# User-specifc inkscape extensions folder for local install
DESTLOCAL=$(HOME)/.config/inkscape/extensions
USER_INKSCAPE_TEMPLATES=$(HOME)/.config/inkscape/templates

.PHONY: help dist install install-local tar_dist_classic tar_dist clean generate_pot update_po mo
help: # Show help for each of the Makefile recipes.
	@grep -E '^[a-zA-Z0-9 -]+:.*#'  Makefile | sort | while read -r l; do printf "\033[1;32m$$(echo $$l | cut -f 1 -d':')\033[00m:$$(echo $$l | cut -f 2- -d'#')\n"; done

mdhelp: # Render help for each of the Makefile recipes in a markdown friendly manner
	@grep -E '^[a-zA-Z0-9 -]+:.*#'  Makefile | sort | while read -r l; do printf " - **$$(echo $$l | cut -f 1 -d':')**:$$(echo $$l | cut -f 2- -d'#')\n"; done

.PHONY: dist
dist: mo # Genearate OS specific packagings and install files (Windows, Linux Distros, etc...)
	cd distribute; sh ./distribute.sh

.PHONY: install
install: mo # Install is used by dist or use this with this command `sudo make install` to install for all users
	mkdir -p $(DEST)
	@# CAUTION: cp -a does not work under fakeroot. Use cp -r instead.
	cp -r cutcutgo $(DEST)
	install -m 755 sendto_cricut.py $(DEST)
	install -m 644 *.inx $(DEST)
	cp -r locale $(LOCALE)

.PHONY: install-local
install-local: mo # Use this with `make install-local` to install just in your user account
	mkdir -p $(DESTLOCAL)
	@# CAUTION: cp -a does not work under fakeroot. Use cp -r instead.
	cp -r cutcutgo $(DESTLOCAL)
	install -m 755 sendto_cricut.py $(DESTLOCAL)
	install -m 644 *.inx $(DESTLOCAL)
	cp -r locale $(DESTLOCAL)

.PHONY: tar_dist_classic
tar_dist_classic: clean mo # Create a compressed tarball archive file (.tar.bz2) that contains the distribution files for the Inkscape Silhouette project. (Using a fixed list defined in $ALL)
	name=$(DISTNAME)-$(VERS); echo "$$name"; echo; \
	tar jcvf $$name.tar.bz2 $(EXCL) --transform="s,^,$$name/," $(ALL)
	grep about_version ./sendto_cricut.inx 
	@echo version should be $(VERS)

.PHONY: tar_dist
tar_dist: mo # Create a compressed tarball archive file (.tar.bz2) that contains the distribution files for the Inkscape Silhouette project. (Using distutils.core parameter like format bztar)
	python3 setup.py sdist --format=bztar
	mv dist/*.tar* .
	rm -rf dist

.PHONY: clean
clean: # Cleanup generated/compiled files and restore project back to nominal state
	rm -f *.orig */*.orig
	rm -rf distribute/$(DISTNAME)
	rm -rf distribute/deb/files
	rm -rf locale

.PHONY: generate_pot
generate_pot: # Updates Portable Object Template
	mkdir -p po/its
	curl -s -o po/its/inx.its https://gitlab.com/inkscape/inkscape/-/raw/master/po/its/inx.its
	xgettext --its po/its/inx.its --no-wrap -o po/inkscape-cutcutgo.pot *.inx
	xgettext --no-wrap -j -o po/inkscape-cutcutgo.pot sendto_cricut.py

.PHONY: update_po
update_po: # Updates localised translation/internationalisation with any new UI language entries from the main Portable Object Template file ./po/inkscape-silhouette.pot
	$(foreach po, $(wildcard po/*.po), \
		msgmerge -q --update --no-wrap $(po) po/inkscape-cutcutgo.pot; )

.PHONY: mo
mo: # Compile transations for different human languages into binary .mo file for internationalisation and localisation purposes. (e.g. ./po/de.po)
	mkdir -p locale
	$(foreach po, $(wildcard po/*.po), \
		mkdir -p locale/$(basename $(notdir $(po)))/LC_MESSAGES; \
		msgfmt -c -o locale/$(basename $(notdir $(po)))/LC_MESSAGES/inkscape-cutcutgo.mo $(po); )
