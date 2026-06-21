(function () {
  "use strict";

  function csrfToken() {
    const csrfMeta = document.querySelector("meta[name='csrf-token']");
    return csrfMeta ? csrfMeta.getAttribute("content") || "" : "";
  }

  function setStatus(element, message, isError) {
    if (!element) {
      return;
    }
    element.textContent = message;
    element.classList.toggle("error-text", Boolean(isError));
  }

  function base64urlToBuffer(value) {
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const base64 = `${value}${padding}`.replace(/-/g, "+").replace(/_/g, "/");
    const binary = window.atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes.buffer;
  }

  function bufferToBase64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function creationOptionsFromJSON(publicKey) {
    const options = { ...publicKey };
    options.challenge = base64urlToBuffer(publicKey.challenge);
    options.user = { ...publicKey.user, id: base64urlToBuffer(publicKey.user.id) };
    if (Array.isArray(publicKey.excludeCredentials)) {
      options.excludeCredentials = publicKey.excludeCredentials.map((credential) => ({
        ...credential,
        id: base64urlToBuffer(credential.id),
      }));
    }
    return options;
  }

  function requestOptionsFromJSON(publicKey) {
    const options = { ...publicKey };
    options.challenge = base64urlToBuffer(publicKey.challenge);
    if (Array.isArray(publicKey.allowCredentials)) {
      options.allowCredentials = publicKey.allowCredentials.map((credential) => ({
        ...credential,
        id: base64urlToBuffer(credential.id),
      }));
    }
    return options;
  }

  function credentialToJSON(credential) {
    const response = credential.response;
    const payload = {
      id: credential.id,
      rawId: bufferToBase64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || null,
      response: {},
    };

    if (response.clientDataJSON) {
      payload.response.clientDataJSON = bufferToBase64url(response.clientDataJSON);
    }
    if (response.attestationObject) {
      payload.response.attestationObject = bufferToBase64url(response.attestationObject);
    }
    if (response.authenticatorData) {
      payload.response.authenticatorData = bufferToBase64url(response.authenticatorData);
    }
    if (response.signature) {
      payload.response.signature = bufferToBase64url(response.signature);
    }
    if (response.userHandle) {
      payload.response.userHandle = bufferToBase64url(response.userHandle);
    }
    if (typeof response.getTransports === "function") {
      payload.response.transports = response.getTransports();
    }
    return payload;
  }

  async function postJSON(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify(body || {}),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Passkey request failed.");
    }
    return payload;
  }

  function browserSupportsPasskeys() {
    return Boolean(window.PublicKeyCredential && navigator.credentials);
  }

  function initializePasskeyRegistration(button) {
    const panel = button.closest("[data-passkey-register-panel]") || document;
    const statusElement = panel.querySelector("[data-passkey-register-status]");

    if (!browserSupportsPasskeys()) {
      button.disabled = true;
      setStatus(statusElement, "Passkeys are not available in this browser.", true);
      return;
    }

    button.addEventListener("click", async () => {
      button.disabled = true;
      setStatus(statusElement, "Waiting for device unlock...", false);
      try {
        const optionsPayload = await postJSON("/config/passkeys/options");
        const credential = await navigator.credentials.create({
          publicKey: creationOptionsFromJSON(optionsPayload.publicKey),
        });
        if (!credential) {
          throw new Error("Passkey setup was canceled.");
        }

        const verificationPayload = await postJSON(
          "/config/passkeys/verify",
          credentialToJSON(credential),
        );
        setStatus(statusElement, verificationPayload.message || "Passkey added.", false);
        window.setTimeout(() => {
          window.location.reload();
        }, 500);
      } catch (error) {
        setStatus(statusElement, error.message || "Passkey setup failed.", true);
        button.disabled = false;
      }
    });
  }

  function initializePasskeyLogin(button) {
    const panel = button.closest("[data-passkey-login-panel]") || document;
    const statusElement = panel.querySelector("[data-passkey-login-status]");

    if (!browserSupportsPasskeys()) {
      button.hidden = true;
      return;
    }

    button.addEventListener("click", async () => {
      button.disabled = true;
      setStatus(statusElement, "Waiting for device unlock...", false);
      try {
        const optionsPayload = await postJSON("/login/passkey/options");
        const credential = await navigator.credentials.get({
          publicKey: requestOptionsFromJSON(optionsPayload.publicKey),
        });
        if (!credential) {
          throw new Error("Passkey login was canceled.");
        }

        const verificationPayload = await postJSON(
          "/login/passkey/verify",
          credentialToJSON(credential),
        );
        window.location.href = verificationPayload.redirect_url || "/home";
      } catch (error) {
        setStatus(statusElement, `${error.message || "Passkey login failed."} Use username and password.`, true);
        button.disabled = false;
      }
    });
  }

  document.querySelectorAll("[data-passkey-register-button]").forEach(initializePasskeyRegistration);
  document.querySelectorAll("[data-passkey-login-button]").forEach(initializePasskeyLogin);
}());
