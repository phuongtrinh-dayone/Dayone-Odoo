/** @odoo-module **/



import { AttachmentCard } from '@mail/components/attachment_card/attachment_card'

console.log(AttachmentCard)
console.log('------------------------------------')
export class AttachmentCard1 extends AttachmentCard {
    get attachmentCard() {
        console.log('------------------------------------')
                return this.props.record;
            }
    
}
AttachmentCard1.template = "leonix_vn_bill_digitization.AttachmentCard";
AttachmentCard1.components = {
    ...AttachmentCard1.components,
}
// AttachmentCard.include({
        
//     init: function () {
//         console.log('----------------------------')
//         console.log(AttachmentCard)
//     },
// })
// export default AttachmentCard;
// // odoo.define('leonix_vn_bill_digitization.AttachmentCard', function(require) {
// //     'use strict';
// //     import { AttachmentCard } from '@mail/components/attachment_card/attachment_card';
    
    
    
// //  });
