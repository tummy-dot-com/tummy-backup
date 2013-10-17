/*
 * Written by Sean Reifschneider <jafo@tummy.com>
 *   Based on code from Adrian "yEnS" Mato Gondelle
 *   http://yensdesign.com/2008/09/how-to-create-a-stunning-and-smooth-popup-using-jquery/
 */

var popuphelp_entityname = null;

function close_popuphelp() {
   if (popuphelp_entityname != null) {
      $("#popuphelpbackground").fadeOut("slow");
      $(popuphelp_entityname).fadeOut("slow");
      popuphelp_entityname = null;
   }
}

function popuphelp(entityname) {
   $(entityname).css({
      "position" : "absolute",
      "top" : (document.documentElement.clientHeight / 2)
            - ($(entityname).height() / 2),
      "left" : (document.documentElement.clientWidth / 2)
            - ($(entityname).width() / 2),
   });

   if (popuphelp_entityname == null) {
      $("#popuphelpbackground").css({ "opacity": "0.7" });
      $("#popuphelpbackground").fadeIn("slow");
      $("#popuphelpbackground").click(function() { close_popuphelp(); });
      $(entityname).fadeIn("slow");
      $(entityname + " .popuphelpclose").click(function() { close_popuphelp(); });
      popuphelp_entityname = entityname;
   }
}
