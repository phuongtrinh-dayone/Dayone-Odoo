/** @odoo-module **/



import { AttachmentCard } from '@mail/components/attachment_card/attachment_card'

export class AttachmentCard1 extends AttachmentCard {
    get attachmentCard() {
                return this.props.record;
            }
    
}
AttachmentCard1.template = "leonix_vn_bill_digitization.AttachmentCard";
AttachmentCard1.components = {
    ...AttachmentCard1.components,
}

