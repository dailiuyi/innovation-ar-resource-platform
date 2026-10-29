-- Navigation icons only: line icons (frontend/src/assets/icons/svg/nav-*.svg). Names, paths, order and permissions are unchanged.
UPDATE sys_menu SET icon='nav-scene'   WHERE menu_id=2000;
UPDATE sys_menu SET icon='nav-list'    WHERE menu_id=2010;
UPDATE sys_menu SET icon='nav-history' WHERE menu_id=2011;
UPDATE sys_menu SET icon='nav-team'    WHERE menu_id=2020;
UPDATE sys_menu SET icon='nav-user'    WHERE menu_id=2001;
UPDATE sys_menu SET icon='nav-signin'  WHERE menu_id=2002;
UPDATE sys_menu SET icon='nav-log'     WHERE menu_id=2003;
