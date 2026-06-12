(function () {
  var siteUrl = "https://vishal2612200.github.io/agentpack/";
  var path = window.location.pathname.replace(/\/$/, "");
  var pageUrl = window.location.href.split("#")[0];
  var title = document.title || "AgentPack";
  var description = document.querySelector('meta[name="description"]');
  var desc = description ? description.getAttribute("content") : "AgentPack is a local context engine for AI coding agents.";

  var graph = [
    {
      "@type": "SoftwareApplication",
      "@id": siteUrl + "#software",
      "name": "AgentPack",
      "applicationCategory": "DeveloperApplication",
      "operatingSystem": "macOS, Linux, Windows",
      "description": "Local context engine for AI coding agents that ranks relevant repo files and builds compact task-focused context packs.",
      "softwareVersion": "0.3.21",
      "license": "https://github.com/vishal2612200/agentpack/blob/main/LICENSE",
      "codeRepository": "https://github.com/vishal2612200/agentpack",
      "url": siteUrl,
      "sameAs": [
        "https://github.com/vishal2612200/agentpack",
        "https://pypi.org/project/agentpack-cli/",
        "https://www.npmjs.com/package/@vishal2612200/agentpack"
      ]
    },
    {
      "@type": "TechArticle",
      "@id": pageUrl + "#article",
      "headline": title,
      "description": desc,
      "url": pageUrl,
      "about": {"@id": siteUrl + "#software"}
    }
  ];

  if (path && path !== "/agentpack") {
    graph.push({
      "@type": "BreadcrumbList",
      "@id": pageUrl + "#breadcrumb",
      "itemListElement": [
        {
          "@type": "ListItem",
          "position": 1,
          "name": "AgentPack Docs",
          "item": siteUrl
        },
        {
          "@type": "ListItem",
          "position": 2,
          "name": title.replace(" - AgentPack", ""),
          "item": pageUrl
        }
      ]
    });
  }

  var script = document.createElement("script");
  script.type = "application/ld+json";
  script.text = JSON.stringify({"@context": "https://schema.org", "@graph": graph});
  document.head.appendChild(script);
}());
