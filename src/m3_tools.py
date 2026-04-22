import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("M3_Logistics_Tools")

def calculate_cbm(payload_json: str) -> str:
    """Calcula o Cubo Metragem (CBM) com exatidão matemática."""
    try:
        data = json.loads(payload_json)
        # Se os dados vierem em cm, divide por 100
        length = float(data.get("length_cm", 0)) / 100
        width = float(data.get("width_cm", 0)) / 100
        height = float(data.get("height_cm", 0)) / 100
        quantity = int(data.get("quantity", 1))
        
        cbm = length * width * height * quantity
        result = {"success": True, "cbm_total": round(cbm, 4), "items": quantity}
        logger.info(f"CBM Calculado: {cbm}")
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

def extract_bl_pl(payload_json: str) -> str:
    """
    Ferramenta OCR de Documentos Logísticos (BL / PL).

    Payload aceito (JSON string):
      {
        "file_path":     "path/to/doc.pdf",   # OU
        "base64_content": "<b64>",            # PDF codificado em base64
        "cross_ref":     true                 # opcional – cruza BL x PL se mixed
      }
    """
    try:
        from src.services.logistics.bl_pl_parser import (
            parse_pdf_file,
            parse_pdf_base64,
            cross_reference,
        )

        data = json.loads(payload_json)
        file_path: str = data.get("file_path", "")
        b64: str = data.get("base64_content", "")
        do_cross_ref: bool = bool(data.get("cross_ref", False))

        if not file_path and not b64:
            return json.dumps({"success": False, "error": "Informe file_path ou base64_content"})

        if b64:
            logger.info("extract_bl_pl: parsing via base64 content")
            parsed = parse_pdf_base64(b64)
        else:
            logger.info(f"extract_bl_pl: parsing file {file_path!r}")
            parsed = parse_pdf_file(file_path)

        result: dict = {"success": True, "extracted_data": parsed}

        if do_cross_ref and parsed.get("doc_type") == "mixed":
            xref = cross_reference(
                bl_data=parsed.get("bl", {}),
                pl_data=parsed.get("pl", {}),
            )
            result["cross_reference"] = xref

        return json.dumps(result)
    except FileNotFoundError as exc:
        return json.dumps({"success": False, "error": str(exc)})
    except ValueError as exc:
        return json.dumps({"success": False, "error": str(exc)})
    except Exception as exc:
        logger.exception("extract_bl_pl failed")
        return json.dumps({"success": False, "error": str(exc)})

def send_whatsapp_webhook(payload_json: str) -> str:
    """
    Envia mensagem WhatsApp via Meta Cloud API.

    Payload aceito (JSON string):
      Modo texto livre (dentro da janela de 24 h):
        {
          "phone":   "+5547999990000",
          "message": "BL MAEU1234567 processado."
        }

      Modo template (proativo, sem restrição de janela):
        {
          "phone":         "+5547999990000",
          "type":          "template",
          "template_name": "notificacao_frete",
          "language":      "pt_BR",          // opcional, default pt_BR
          "components": [                     // opcional
            {
              "type": "body",
              "parameters": [{"type": "text", "text": "MAEU1234567"}]
            }
          ]
        }
    """
    try:
        from src.services.whatsapp.meta_client import (
            send_text,
            send_template,
            WhatsAppAPIError,
        )

        data = json.loads(payload_json)
        phone: str = data.get("phone", "")
        msg_type: str = data.get("type", "text")

        if not phone:
            return json.dumps({"success": False, "error": "Campo 'phone' obrigatório"})

        if msg_type == "template":
            template_name = data.get("template_name", "")
            if not template_name:
                return json.dumps({"success": False, "error": "Campo 'template_name' obrigatório para type=template"})
            result = send_template(
                phone=phone,
                template_name=template_name,
                language=data.get("language", "pt_BR"),
                components=data.get("components"),
            )
        else:
            message: str = data.get("message", "")
            if not message:
                return json.dumps({"success": False, "error": "Campo 'message' obrigatório para type=text"})
            result = send_text(phone=phone, message=message)

        msg_id = result.get("messages", [{}])[0].get("id", "")
        logger.info(f"WhatsApp enviado → {phone} | msg_id={msg_id}")
        return json.dumps({"success": True, "message_id": msg_id, "to": phone})

    except WhatsAppAPIError as exc:
        return json.dumps({"success": False, "error": str(exc), "status_code": exc.status_code})
    except Exception as exc:
        logger.exception("send_whatsapp_webhook falhou")
        return json.dumps({"success": False, "error": str(exc)})

# Mapping dictionary for dynamic dispatch
TOOLS_REGISTRY = {
    "calculate_cbm": calculate_cbm,
    "extract_bl_pl": extract_bl_pl,
    "send_whatsapp_webhook": send_whatsapp_webhook
}
