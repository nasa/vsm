<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
xmlns:xsl="http://www.w3.org/1999/XSL/Transform">

<xsl:template match="/web_commanding_servers">
  <html>
    <head><title>VSM Status</title></head>
    <body>
      <xsl:for-each select="group">
          <h1><xsl:value-of select="./@type"/></h1>
            <table>
              <tr>
                <th>Host</th>
                <th>Port</th>
                <th>Clients</th>
                <th>Cameras</th>
              </tr>
              <xsl:for-each select="wcs">
                <xsl:sort select="."/>
                <xsl:sort select="./@port" data-type="number"/>
                <tr>
                  <td style="white-space:pre">
                    <xsl:for-each select="address">
                      <xsl:sort select="./@ip" data-type="number"/>
                      <xsl:value-of select="./@host"/>
                      <xsl:text> (</xsl:text>
                      <xsl:value-of select="./@ip"/>
                      <xsl:text>)&#xa;</xsl:text>
                    </xsl:for-each>
                  </td>
                  <td><xsl:value-of select="./@port"/></td>
                  <td><xsl:value-of select="./@num_clients"/></td>
                  <td>
                    <xsl:for-each select="camera">
                      <xsl:choose>
                        <xsl:when test="@rendered = 'True'">
                          <strong><xsl:value-of select="."/></strong>
                        </xsl:when>
                        <xsl:otherwise>
                          <xsl:value-of select="."/>
                        </xsl:otherwise>
                      </xsl:choose>
                      <xsl:text> | </xsl:text>
                    </xsl:for-each>
                  </td>
                </tr>
              </xsl:for-each>
            </table>
      </xsl:for-each>
    </body>
  </html>
</xsl:template>

</xsl:stylesheet>
