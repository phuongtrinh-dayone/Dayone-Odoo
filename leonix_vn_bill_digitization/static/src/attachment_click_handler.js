odoo.define('leonix_vn_bill_digitization.attachment_click_handler', function (require) {
    "use strict";

    var form_widget = require('web.form_widgets');

    form_widget.Widget.include({
        on_attachment_click: function (attachment_id) {
            var self = this;
            this._rpc({
                model: 'account.move',
                method: 'on_attachment_click',
                args: [attachment_id],
            }).then(function (result) {
                if (result && result.res_id) {
                    result.views = [[false, 'form']];
                    result.view_id = false;
                    result.view_type = 'form';
                    result.flags = {
                        'form': {'action_buttons': true},
                    };
                    result.res_id = result.res_id[0];
                    result.target = 'new';
                    // result.context = {
                    //     'default_html_field_name': result.context.default_html_field_name,
                    // };
                    self.do_action(result);
                } else {
                    // Dialog.alert(self, "Attachment details not found.");
                }
            });
        }
    });
});