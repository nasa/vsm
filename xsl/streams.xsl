<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
xmlns:xsl="http://www.w3.org/1999/XSL/Transform">

<xsl:template match="/streams">
  <html>
    <head><title>VSM Streams</title></head>
    <body>
      <xsl:for-each select="set">
        <p>
          <xsl:for-each select="stream">
            <a href="{@url}">
              <xsl:value-of select="."/>
            </a>
          </xsl:for-each>
        </p>
      </xsl:for-each>
    </body>
  </html>
</xsl:template>

</xsl:stylesheet>
