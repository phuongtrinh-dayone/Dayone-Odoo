/** @odoo-module **/
import { registerPatch } from '@mail/model/model_core';
var core = require('web.core');
var session = require('web.session');
registerPatch({
    name: 'AttachmentCard',
    recordMethods: {
        
        onClickAttachment(ev) {
            const model_name = this.attachment.originThread.model
            if (this.attachment.mimetype.indexOf('xml') != -1 && model_name == 'account.move') {
                var action = {
                    name: 'Invoice Preview',
                    type: 'ir.actions.act_window',
                    views: [[false, 'form']],
                    res_model: 'account.preview.xml.wizard',
                    target: 'new',
                    context: {
                        active_id: this.attachment.id // Giá trị active_id từ JavaScript
                    }
                };
                core.bus.trigger('do-action', {
                    action: action,
                });
            }
        },
    }
});
