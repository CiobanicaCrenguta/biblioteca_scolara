/* Atelierul bibliotecarului: etichete cu completare automată.
   Câmpul rămâne un input obișnuit cu valori separate prin virgulă, deci
   formularul funcționează și fără JavaScript. Scriptul doar îl îmbracă. */

(function () {
  "use strict";

  const RUTE = {
    autori: "/gestiune/autori/",
    subiecte: "/gestiune/teme/"
  };

  function imparte(valoare) {
    return (valoare || "")
      .split(",")
      .map(function (s) { return s.trim().replace(/\s+/g, " "); })
      .filter(function (s) { return s.length > 0; });
  }

  function construieste(input) {
    const fel = input.dataset.completare;
    const ruta = RUTE[fel];
    if (!ruta) { return; }

    const cutie = document.createElement("div");
    cutie.className = "etichete";
    const zona = document.createElement("div");
    zona.className = "etichete-lista";
    const scris = document.createElement("input");
    scris.type = "text";
    scris.className = "etichete-scris";
    scris.setAttribute("autocomplete", "off");
    scris.placeholder = input.placeholder || "scrie și apasă Enter";
    const sugestii = document.createElement("ul");
    sugestii.className = "sugestii";
    sugestii.hidden = true;

    cutie.appendChild(zona);
    cutie.appendChild(scris);
    cutie.appendChild(sugestii);
    input.parentNode.insertBefore(cutie, input.nextSibling);
    input.type = "hidden";

    let valori = imparte(input.value);

    function sincronizeaza() {
      input.value = valori.join(", ");
      zona.textContent = "";
      valori.forEach(function (nume, i) {
        const eticheta = document.createElement("span");
        eticheta.className = "eticheta";
        eticheta.textContent = nume;
        const sterge = document.createElement("button");
        sterge.type = "button";
        sterge.className = "eticheta-x";
        sterge.setAttribute("aria-label", "Scoate " + nume);
        sterge.textContent = "×";
        sterge.addEventListener("click", function () {
          valori.splice(i, 1);
          sincronizeaza();
          scris.focus();
        });
        eticheta.appendChild(sterge);
        zona.appendChild(eticheta);
      });
    }

    function adauga(nume) {
      const curat = (nume || "").trim().replace(/\s+/g, " ");
      if (!curat) { return; }
      const exista = valori.some(function (v) {
        return v.toLowerCase() === curat.toLowerCase();
      });
      if (!exista) { valori.push(curat); }
      scris.value = "";
      ascunde();
      sincronizeaza();
    }

    function ascunde() {
      sugestii.hidden = true;
      sugestii.textContent = "";
    }

    let ceas = null;
    scris.addEventListener("input", function () {
      const q = scris.value.trim();
      clearTimeout(ceas);
      if (q.length < 2) { ascunde(); return; }
      ceas = setTimeout(function () { intreaba(q); }, 180);
    });

    function intreaba(q) {
      fetch(ruta + "?q=" + encodeURIComponent(q), {
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then(function (r) { return r.ok ? r.json() : { rezultate: [] }; })
        .then(function (date) { arata(date.rezultate || [], q); })
        .catch(function () { ascunde(); });
    }

    function arata(rezultate, q) {
      sugestii.textContent = "";
      const potrivireExacta = rezultate.some(function (r) {
        return r.nume.toLowerCase() === q.toLowerCase();
      });

      rezultate.forEach(function (r) {
        const li = document.createElement("li");
        li.textContent = r.nume;
        li.addEventListener("mousedown", function (ev) {
          ev.preventDefault();
          adauga(r.nume);
        });
        sugestii.appendChild(li);
      });

      if (!potrivireExacta) {
        const li = document.createElement("li");
        li.className = "sugestie-noua";
        li.textContent = "Adaugă „" + q + "” ca intrare nouă";
        li.addEventListener("mousedown", function (ev) {
          ev.preventDefault();
          adauga(q);
        });
        sugestii.appendChild(li);
      }
      sugestii.hidden = sugestii.children.length === 0;
    }

    scris.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === ",") {
        ev.preventDefault();
        const prima = sugestii.querySelector("li:not(.sugestie-noua)");
        adauga(prima && scris.value.trim().length >= 2 ? prima.textContent : scris.value);
      } else if (ev.key === "Backspace" && !scris.value && valori.length) {
        valori.pop();
        sincronizeaza();
      } else if (ev.key === "Escape") {
        ascunde();
      }
    });

    scris.addEventListener("blur", function () {
      setTimeout(function () { if (scris.value.trim()) { adauga(scris.value); } ascunde(); }, 120);
    });

    sincronizeaza();
  }

  document.querySelectorAll("input[data-completare]").forEach(construieste);

  // Arată doar câmpul potrivit tipului de stocare ales.
  const stocare = document.querySelector("[name='resursa_stocare']");
  if (stocare) {
    const comuta = function () {
      document.querySelectorAll("[data-stocare]").forEach(function (zona) {
        zona.hidden = zona.dataset.stocare !== stocare.value;
      });
    };
    stocare.addEventListener("change", comuta);
    comuta();
  }
})();
