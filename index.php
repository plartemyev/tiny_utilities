<?php
session_start();
$myPHPparams = file_get_contents("/etc/php.d/redis.ini");
?>

<!DOCTYPE html>
<html>
<body>

<?php
if(isset($_SESSION["renderCounter"])){
  $_SESSION["renderCounter"] += 1;}
else{$_SESSION["renderCounter"] = 1;}

echo "<p>This page was rendered " . $_SESSION["renderCounter"] . " times in this session.</p>";
echo "<p>My custom PHP.INI paremeters is:</p>";
echo "<p>" . $myPHPparams . "</p>";
?>

</body>
</html>
